import React, { useEffect, useState } from 'react'
import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  closestCorners,
  useSensor,
  useSensors,
} from '@dnd-kit/core'
import {
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { format, isBefore, parseISO, startOfDay } from 'date-fns'
import { fr } from 'date-fns/locale'
import { AlertCircle, Loader2, Plus, Trash2, X } from 'lucide-react'

import {
  addComment,
  createTicket,
  deleteTicket,
  getTicket,
  messageErreur,
  patchTicket,
} from '../api/client'
import { COLONNES, useTickets } from '../hooks/useTickets'

const PRIORITES = [
  { id: 'low', label: 'Basse' },
  { id: 'medium', label: 'Moyenne' },
  { id: 'high', label: 'Haute' },
  { id: 'urgent', label: 'Urgente' },
]

const COULEUR_PRIORITE = {
  low: 'bg-ink-subtle',
  medium: 'bg-primary',
  high: 'bg-warning',
  urgent: 'bg-danger',
}

/** Initiales d'un nom complet, pour la pastille d'assigné. */
function initiales(nom) {
  if (!nom) return '—'
  return nom
    .split(/[\s.]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((m) => m[0].toUpperCase())
    .join('')
}

function Carte({ ticket, utilisateurs, tags, onOuvrir }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: ticket.id })

  const assigne = utilisateurs.find((u) => u.id === ticket.assignee_id)
  const enRetard =
    ticket.due_date &&
    ticket.status !== 'done' &&
    isBefore(parseISO(ticket.due_date), startOfDay(new Date()))

  return (
    <article
      ref={setNodeRef}
      {...attributes}
      {...listeners}
      onClick={() => onOuvrir(ticket.id)}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className={`bg-card border-2 border-line rounded-2xl p-4 cursor-grab active:cursor-grabbing ${
        isDragging ? 'opacity-40' : ''
      }`}
    >
      <div className="flex items-start justify-between gap-2 mb-2">
        <span className="text-[9px] font-black uppercase tracking-widest text-ink-muted">
          #{ticket.id}
        </span>
        <span
          className={`${COULEUR_PRIORITE[ticket.priority]} w-2 h-2 rounded-full shrink-0 mt-1`}
          title={PRIORITES.find((p) => p.id === ticket.priority)?.label}
        />
      </div>

      <p className="text-sm font-black leading-snug line-clamp-2 mb-3">{ticket.title}</p>

      <div className="flex items-center justify-between gap-2">
        <div className="flex gap-1 flex-wrap">
          {ticket.tag_ids.map((id) => {
            const tag = tags.find((t) => t.id === id)
            if (!tag) return null
            return (
              <span
                key={id}
                className="w-2 h-2 rounded-full"
                style={{ backgroundColor: tag.color || 'var(--text-muted)' }}
                title={tag.name}
              />
            )
          })}
        </div>
        <div className="flex items-center gap-2">
          {ticket.due_date && (
            <span
              className={`text-[9px] font-black uppercase tracking-widest ${
                enRetard ? 'text-danger' : 'text-ink-muted'
              }`}
            >
              {format(parseISO(ticket.due_date), 'd MMM', { locale: fr })}
            </span>
          )}
          {assigne && (
            <span
              className="bg-primary-soft text-primary text-[9px] font-black w-6 h-6 rounded-full flex items-center justify-center shrink-0"
              title={assigne.full_name}
            >
              {initiales(assigne.full_name)}
            </span>
          )}
        </div>
      </div>
    </article>
  )
}

function Colonne({ colonne, cartes, utilisateurs, tags, onOuvrir }) {
  return (
    <section className="flex-1 min-w-[260px] flex flex-col">
      <header className="flex items-center justify-between mb-4 px-1">
        <h3 className="text-[10px] font-black uppercase tracking-widest text-ink-muted">
          {colonne.label}
        </h3>
        <span className="text-[10px] font-black text-ink-subtle">{cartes.length}</span>
      </header>
      <SortableContext items={cartes.map((t) => t.id)} strategy={verticalListSortingStrategy}>
        <div className="flex flex-col gap-3 bg-input rounded-[20px] p-3 min-h-[140px] flex-1">
          {cartes.map((t) => (
            <Carte
              key={t.id}
              ticket={t}
              utilisateurs={utilisateurs}
              tags={tags}
              onOuvrir={onOuvrir}
            />
          ))}
        </div>
      </SortableContext>
    </section>
  )
}

function Tiroir({ ticketId, utilisateurs, tags, currentUser, onFermer, onChange }) {
  const [detail, setDetail] = useState(null)
  const [commentaire, setCommentaire] = useState('')
  const [erreur, setErreur] = useState(null)

  const charger = async () => {
    try {
      setDetail(await getTicket(ticketId))
    } catch (err) {
      setErreur(messageErreur(err, 'Ticket introuvable'))
    }
  }

  useEffect(() => {
    charger()
    const auClavier = (e) => e.key === 'Escape' && onFermer()
    window.addEventListener('keydown', auClavier)
    return () => window.removeEventListener('keydown', auClavier)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticketId])

  const modifier = async (champs) => {
    try {
      await patchTicket(ticketId, champs)
      await charger()
      onChange()
    } catch (err) {
      setErreur(messageErreur(err, "La modification n'a pas été enregistrée"))
    }
  }

  const commenter = async (e) => {
    e.preventDefault()
    if (!commentaire.trim()) return
    await addComment(ticketId, commentaire)
    setCommentaire('')
    await charger()
  }

  const supprimer = async () => {
    await deleteTicket(ticketId)
    onChange()
    onFermer()
  }

  return (
    <aside
      role="dialog"
      aria-label="Détail du ticket"
      className="fixed top-0 right-0 bottom-0 w-full sm:w-[460px] bg-card border-l-2 border-line z-50 overflow-y-auto p-8"
    >
      <div className="flex items-start justify-between gap-4 mb-6">
        <span className="text-[10px] font-black uppercase tracking-widest text-ink-muted">
          Ticket #{ticketId}
        </span>
        <button onClick={onFermer} aria-label="Fermer" className="text-ink-muted hover:text-ink">
          <X size={18} />
        </button>
      </div>

      {erreur && (
        <div role="alert" className="alert-error mb-5">
          <AlertCircle size={16} /> {erreur}
        </div>
      )}

      {!detail ? (
        <Loader2 className="animate-spin text-ink-muted" size={20} />
      ) : (
        <div className="flex flex-col gap-6">
          <input
            className="form-input text-base"
            defaultValue={detail.title}
            onBlur={(e) => e.target.value !== detail.title && modifier({ title: e.target.value })}
          />

          <textarea
            className="form-input min-h-[120px]"
            placeholder="Description"
            defaultValue={detail.description || ''}
            onBlur={(e) =>
              e.target.value !== (detail.description || '') &&
              modifier({ description: e.target.value })
            }
          />

          <div className="grid grid-cols-2 gap-4">
            <div className="form-group">
              <label htmlFor="priorite">Priorité</label>
              <select
                id="priorite"
                className="form-input"
                value={detail.priority}
                onChange={(e) => modifier({ priority: e.target.value })}
              >
                {PRIORITES.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="form-group">
              <label htmlFor="assigne">Assigné à</label>
              <select
                id="assigne"
                className="form-input"
                value={detail.assignee_id ?? ''}
                onChange={(e) =>
                  modifier({ assignee_id: e.target.value ? Number(e.target.value) : null })
                }
              >
                <option value="">Personne</option>
                {utilisateurs.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.full_name}
                  </option>
                ))}
              </select>
            </div>
            <div className="form-group col-span-2">
              <label htmlFor="echeance">Échéance</label>
              <input
                id="echeance"
                type="date"
                className="form-input"
                defaultValue={detail.due_date || ''}
                onChange={(e) => modifier({ due_date: e.target.value || null })}
              />
            </div>
          </div>

          <div className="form-group">
            <label>Étiquettes</label>
            <div className="flex flex-wrap gap-2">
              {tags.map((tag) => {
                const actif = detail.tag_ids.includes(tag.id)
                return (
                  <button
                    key={tag.id}
                    type="button"
                    onClick={() =>
                      modifier({
                        tag_ids: actif
                          ? detail.tag_ids.filter((id) => id !== tag.id)
                          : [...detail.tag_ids, tag.id],
                      })
                    }
                    className={`px-3 py-1 rounded-full text-[10px] font-black uppercase tracking-widest border-2 transition-all ${
                      actif ? 'border-primary text-primary' : 'border-line text-ink-muted'
                    }`}
                  >
                    {tag.name}
                  </button>
                )
              })}
            </div>
          </div>

          <div>
            <h4 className="text-[10px] font-black uppercase tracking-widest text-ink-muted mb-3">
              Commentaires
            </h4>
            <ul className="flex flex-col gap-3 mb-4">
              {detail.comments.map((c) => (
                <li key={c.id} className="bg-input rounded-2xl px-4 py-3 text-sm">
                  <span className="font-black text-[10px] uppercase tracking-widest text-ink-muted">
                    {utilisateurs.find((u) => u.id === c.author_id)?.full_name ?? 'Inconnu'}
                  </span>
                  <p className="mt-1">{c.body}</p>
                </li>
              ))}
            </ul>
            <form onSubmit={commenter} className="flex gap-2">
              <input
                className="form-input"
                placeholder="Ajouter un commentaire…"
                value={commentaire}
                onChange={(e) => setCommentaire(e.target.value)}
              />
              <button type="submit" className="btn-primary" style={{ borderRadius: '9999px' }}>
                OK
              </button>
            </form>
          </div>

          <details>
            <summary className="text-[10px] font-black uppercase tracking-widest text-ink-muted cursor-pointer">
              Historique ({detail.events.length})
            </summary>
            <ul className="mt-3 flex flex-col gap-1 text-xs text-ink-muted">
              {detail.events.map((e) => (
                <li key={e.id}>
                  {format(parseISO(e.created_at), 'd MMM HH:mm', { locale: fr })} — {e.kind}
                  {e.payload ? ` (${e.payload})` : ''}
                </li>
              ))}
            </ul>
          </details>

          {currentUser.is_admin && (
            <button
              onClick={supprimer}
              className="flex items-center gap-2 text-[10px] font-black uppercase tracking-widest text-ink-muted hover:text-danger self-start"
            >
              <Trash2 size={14} /> Supprimer ce ticket
            </button>
          )}
        </div>
      )}
    </aside>
  )
}

export function Tickets({ currentUser }) {
  const {
    board,
    tags,
    utilisateurs,
    loading,
    error,
    toast,
    filtres,
    setFiltres,
    recharger,
    deplacer,
  } = useTickets()

  const [ouvert, setOuvert] = useState(null)
  const [nouveauTitre, setNouveauTitre] = useState('')
  // Sous 768 px le glisser-déposer est remplacé par un onglet de statut.
  const [colonneMobile, setColonneMobile] = useState('todo')

  const sensors = useSensors(
    // 8 px avant d'armer le glissement : sans ce seuil, un clic sur la carte
    // pour ouvrir le tiroir déclencherait un déplacement.
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )

  const colonneDe = (id) =>
    COLONNES.find((c) => (board[c.id] ?? []).some((t) => t.id === id))?.id

  const auDepot = ({ active, over }) => {
    if (!over || active.id === over.id) return
    const cible = colonneDe(over.id) ?? over.id
    if (!COLONNES.some((c) => c.id === cible)) return
    const dansCible = board[cible] ?? []
    const surUneCarte = dansCible.some((t) => t.id === over.id)
    deplacer(active.id, cible, surUneCarte ? over.id : null)
  }

  const creer = async (e) => {
    e.preventDefault()
    if (!nouveauTitre.trim()) return
    await createTicket({ title: nouveauTitre.trim() })
    setNouveauTitre('')
    recharger()
  }

  if (loading) {
    return (
      <main className="p-8 flex items-center gap-3 text-ink-muted">
        <Loader2 className="animate-spin" size={20} />
        <span className="text-xs font-black uppercase tracking-widest">Chargement du tableau…</span>
      </main>
    )
  }

  if (error) {
    return (
      <main className="p-8">
        <div role="alert" className="alert-error max-w-2xl">
          <AlertCircle size={18} /> {error}
        </div>
      </main>
    )
  }

  return (
    <main className="p-8 w-full">
      <h2 className="text-5xl font-black uppercase tracking-tighter mb-6">Tickets</h2>

      <div className="flex items-center gap-2 flex-wrap mb-6">
        <form onSubmit={creer} className="flex gap-2">
          <div className="w-[240px]">
          <input
            className="form-input"
            placeholder="Nouveau ticket…"
            value={nouveauTitre}
            onChange={(e) => setNouveauTitre(e.target.value)}
          />
          </div>
          <button type="submit" aria-label="Créer" className="btn-primary" style={{ borderRadius: '9999px' }}>
            <Plus size={16} />
          </button>
        </form>

        <button
          onClick={() => setFiltres({ ...filtres, mine: !filtres.mine })}
          className={`px-5 py-3 rounded-2xl font-black uppercase text-[10px] tracking-widest border-2 transition-all ${
            filtres.mine ? 'border-primary text-primary' : 'border-line text-ink-muted'
          }`}
        >
          Mes tickets
        </button>

        <div className="w-[170px]">
        <select
          className="form-input"
          value={filtres.tag_id}
          onChange={(e) => setFiltres({ ...filtres, tag_id: e.target.value })}
        >
          <option value="">Toutes étiquettes</option>
          {tags.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name}
            </option>
          ))}
        </select>
        </div>

        <div className="w-[180px]">
        <select
          className="form-input"
          value={filtres.priority}
          onChange={(e) => setFiltres({ ...filtres, priority: e.target.value })}
        >
          <option value="">Toutes priorités</option>
          {PRIORITES.map((p) => (
            <option key={p.id} value={p.id}>
              {p.label}
            </option>
          ))}
        </select>
        </div>

        <div className="w-[200px]">
          <input
            className="form-input"
            placeholder="Rechercher…"
            value={filtres.q}
            onChange={(e) => setFiltres({ ...filtres, q: e.target.value })}
          />
        </div>
      </div>

      {/* Écran large : les quatre colonnes, glisser-déposer actif. */}
      <div className="hidden md:block">
        <DndContext sensors={sensors} collisionDetection={closestCorners} onDragEnd={auDepot}>
          <div className="flex gap-4 items-stretch">
            {COLONNES.map((c) => (
              <Colonne
                key={c.id}
                colonne={c}
                cartes={board[c.id] ?? []}
                utilisateurs={utilisateurs}
                tags={tags}
                onOuvrir={setOuvert}
              />
            ))}
          </div>
        </DndContext>
      </div>

      {/* Mobile : une colonne à la fois, déplacement par menu. */}
      <div className="md:hidden">
        <div className="flex gap-2 mb-4 overflow-x-auto custom-scrollbar pb-2">
          {COLONNES.map((c) => (
            <button
              key={c.id}
              onClick={() => setColonneMobile(c.id)}
              className={`shrink-0 px-4 py-2 rounded-2xl text-[10px] font-black uppercase tracking-widest border-2 ${
                colonneMobile === c.id ? 'border-primary text-primary' : 'border-line text-ink-muted'
              }`}
            >
              {c.label} ({(board[c.id] ?? []).length})
            </button>
          ))}
        </div>
        <div className="flex flex-col gap-3">
          {(board[colonneMobile] ?? []).map((t) => (
            <div key={t.id} className="bg-card border-2 border-line rounded-2xl p-4">
              <button onClick={() => setOuvert(t.id)} className="text-left w-full">
                <span className="text-[9px] font-black uppercase tracking-widest text-ink-muted">
                  #{t.id}
                </span>
                <p className="text-sm font-black leading-snug">{t.title}</p>
              </button>
              <select
                className="form-input mt-3"
                value=""
                onChange={(e) => e.target.value && deplacer(t.id, e.target.value)}
              >
                <option value="">Déplacer vers…</option>
                {COLONNES.filter((c) => c.id !== t.status).map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.label}
                  </option>
                ))}
              </select>
            </div>
          ))}
        </div>
      </div>

      {toast && (
        <div
          role="alert"
          className="fixed bottom-6 right-6 bg-danger text-on-primary px-6 py-4 rounded-2xl text-sm font-black shadow-xl z-50"
        >
          {toast}
        </div>
      )}

      {ouvert && (
        <Tiroir
          ticketId={ouvert}
          utilisateurs={utilisateurs}
          tags={tags}
          currentUser={currentUser}
          onFermer={() => setOuvert(null)}
          onChange={recharger}
        />
      )}
    </main>
  )
}
