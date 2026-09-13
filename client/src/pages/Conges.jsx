/*
 * Congés — intégrés à l'écran Mon CRA plutôt qu'isolés dans un onglet.
 *
 * Deux morceaux : une fenêtre de demande, ouverte depuis la barre d'actions
 * du CRA, et un bloc soldes / demandes posé sous le calendrier. Poser un
 * congé et remplir son CRA sont le même geste — les séparer obligeait à
 * naviguer entre deux écrans pour une seule journée d'absence.
 */

import React, { useMemo, useState } from 'react'
import { format, parseISO } from 'date-fns'
import { fr } from 'date-fns/locale'
import { AlertCircle, Check, Loader2, X } from 'lucide-react'

import { messageErreur } from '../api/client'
import { compterJours } from '../lib/decompte'
import { useConges } from '../hooks/useConges'

const LIBELLES_STATUT = {
  pending: 'En attente',
  approved: 'Approuvé',
  rejected: 'Refusé',
  cancelled: 'Annulé',
}

const COULEURS_STATUT = {
  pending: 'bg-warning',
  approved: 'bg-success',
  rejected: 'bg-danger',
  cancelled: 'bg-ink-subtle',
}

const jour = (iso) => format(parseISO(iso), 'd MMM yyyy', { locale: fr })

function Badge({ statut }) {
  return (
    <span
      className={`${COULEURS_STATUT[statut]} text-on-primary text-[9px] px-2 py-0.5 rounded-full font-black uppercase tracking-widest shrink-0`}
    >
      {LIBELLES_STATUT[statut] ?? statut}
    </span>
  )
}

function Carte({ titre, children, className = '' }) {
  return (
    <section className={`bg-card rounded-[20px] p-6 border-2 border-line ${className}`}>
      <h3 className="text-[10px] font-black uppercase tracking-widest text-ink-muted mb-5">
        {titre}
      </h3>
      {children}
    </section>
  )
}

/** Fenêtre de demande, ouverte depuis la barre d'actions du CRA. */
export function DemandeCongeModal({ conges, onFermer }) {
  const { types, feries, deposer } = conges
  const [form, setForm] = useState({
    leave_type_id: '',
    start_date: '',
    end_date: '',
    start_half: '',
    end_half: '',
    reason: '',
  })
  const [envoi, setEnvoi] = useState(false)
  const [erreur, setErreur] = useState(null)

  // Décompte affiché en direct. Le serveur recalcule et fait foi.
  const decompte = useMemo(
    () => compterJours(form.start_date, form.end_date, feries, form.start_half, form.end_half),
    [form.start_date, form.end_date, form.start_half, form.end_half, feries],
  )

  const soumettre = async (e) => {
    e.preventDefault()
    setErreur(null)
    setEnvoi(true)
    try {
      await deposer({
        ...form,
        leave_type_id: Number(form.leave_type_id),
        start_half: form.start_half || null,
        end_half: form.end_half || null,
        reason: form.reason || null,
      })
      onFermer()
    } catch (err) {
      setErreur(messageErreur(err, "La demande n'a pas pu être enregistrée"))
    } finally {
      setEnvoi(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-inverse/40 p-0 sm:p-6"
      onClick={onFermer}
    >
      <div
        role="dialog"
        aria-label="Demande de congé"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => e.key === 'Escape' && onFermer()}
        className="bg-card w-full sm:max-w-lg rounded-t-[28px] sm:rounded-[28px] p-8 max-h-[92vh] overflow-y-auto"
      >
        <div className="flex items-start justify-between gap-4 mb-6">
          <h2 className="text-xl font-black uppercase tracking-tighter">Demande de congé</h2>
          <button onClick={onFermer} aria-label="Fermer" className="text-ink-muted hover:text-ink">
            <X size={18} />
          </button>
        </div>

        {erreur && (
          <div role="alert" className="alert-error mb-5">
            <AlertCircle size={16} /> {erreur}
          </div>
        )}

        <form onSubmit={soumettre} className="flex flex-col gap-5">
          <div className="form-group">
            <label htmlFor="type">Type d'absence</label>
            <select
              id="type"
              className="form-input"
              required
              value={form.leave_type_id}
              onChange={(e) => setForm({ ...form, leave_type_id: e.target.value })}
            >
              <option value="">Choisir…</option>
              {types.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.label}
                </option>
              ))}
            </select>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="form-group">
              <label htmlFor="debut">Du</label>
              <input
                id="debut"
                type="date"
                className="form-input"
                required
                value={form.start_date}
                onChange={(e) => setForm({ ...form, start_date: e.target.value })}
              />
            </div>
            <div className="form-group">
              <label htmlFor="debut-moitie">Départ</label>
              <select
                id="debut-moitie"
                className="form-input"
                value={form.start_half}
                onChange={(e) => setForm({ ...form, start_half: e.target.value })}
              >
                <option value="">Journée entière</option>
                <option value="am">Matin</option>
                <option value="pm">Après-midi</option>
              </select>
            </div>
            <div className="form-group">
              <label htmlFor="fin">Au</label>
              <input
                id="fin"
                type="date"
                className="form-input"
                required
                value={form.end_date}
                onChange={(e) => setForm({ ...form, end_date: e.target.value })}
              />
            </div>
            <div className="form-group">
              <label htmlFor="fin-moitie">Retour</label>
              <select
                id="fin-moitie"
                className="form-input"
                value={form.end_half}
                onChange={(e) => setForm({ ...form, end_half: e.target.value })}
              >
                <option value="">Journée entière</option>
                <option value="am">Matin</option>
                <option value="pm">Après-midi</option>
              </select>
            </div>
          </div>

          <div className="form-group">
            <label htmlFor="motif">Motif (facultatif)</label>
            <input
              id="motif"
              type="text"
              className="form-input"
              value={form.reason}
              onChange={(e) => setForm({ ...form, reason: e.target.value })}
            />
          </div>

          <p aria-live="polite" className="text-sm font-black uppercase tracking-widest text-ink-muted">
            {decompte === null
              ? 'Décompte : —'
              : `Décompte : ${decompte} jour${decompte > 1 ? 's' : ''}`}
          </p>

          <button
            type="submit"
            className="btn-primary"
            disabled={envoi || !decompte}
            style={{ borderRadius: '9999px' }}
          >
            {envoi ? 'Envoi…' : 'Déposer la demande'}
          </button>
        </form>
      </div>
    </div>
  )
}

/** Soldes, demandes et absences de l'équipe, affichés sous le calendrier. */
export function BlocConges({ conges, currentUser }) {
  const {
    annee,
    loading,
    error,
    types,
    mesDemandes,
    enAttente,
    soldes,
    equipe,
    utilisateurs,
    decider,
    annuler,
  } = conges

  const nomsTypes = useMemo(
    () => Object.fromEntries(types.map((t) => [t.id, t.label])),
    [types],
  )

  if (loading) {
    return (
      <div className="flex items-center gap-3 text-ink-muted mt-10">
        <Loader2 className="animate-spin" size={18} />
        <span className="text-xs font-black uppercase tracking-widest">Chargement des congés…</span>
      </div>
    )
  }

  if (error) {
    return (
      <div role="alert" className="alert-error mt-10 max-w-2xl">
        <AlertCircle size={18} /> {error}
      </div>
    )
  }

  return (
    <div className="mt-10 flex flex-col gap-6">
      <h2 className="text-3xl font-black uppercase tracking-tighter">Congés</h2>

      {currentUser.is_admin && enAttente.length > 0 && (
        <Carte titre={`À valider — ${enAttente.length} demande(s)`}>
          <ul className="flex flex-col gap-3">
            {enAttente.map((d) => (
              <li
                key={d.id}
                className="flex items-center justify-between gap-4 bg-input rounded-2xl px-5 py-4 flex-wrap"
              >
                <div className="text-sm min-w-0">
                  <span className="font-black">
                    {utilisateurs.find((u) => u.id === d.user_id)?.full_name ?? `#${d.user_id}`}
                  </span>
                  <span className="text-ink-muted">
                    {' '}— {nomsTypes[d.leave_type_id]} · du {jour(d.start_date)} au{' '}
                    {jour(d.end_date)} · <strong>{d.days} j</strong>
                  </span>
                  {d.reason && <p className="text-xs text-ink-muted mt-1 italic">{d.reason}</p>}
                </div>
                <div className="flex gap-2 shrink-0">
                  <button
                    onClick={() => decider(d.id, true)}
                    aria-label="Approuver"
                    className="bg-success text-on-primary p-2 rounded-xl"
                  >
                    <Check size={16} />
                  </button>
                  <button
                    onClick={() => decider(d.id, false)}
                    aria-label="Refuser"
                    className="bg-danger text-on-primary p-2 rounded-xl"
                  >
                    <X size={16} />
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </Carte>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Carte titre={`Mes soldes ${annee}`}>
          {soldes.length === 0 ? (
            <p className="text-sm text-ink-muted">
              Aucun droit saisi pour {annee}. Un administrateur les pose depuis l'écran
              Collaborateurs.
            </p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-[9px] uppercase tracking-widest text-ink-muted text-left">
                  <th className="pb-3">Type</th>
                  <th className="pb-3 text-right">Acquis</th>
                  <th className="pb-3 text-right">Pris</th>
                  <th className="pb-3 text-right">En attente</th>
                  <th className="pb-3 text-right">Restant</th>
                </tr>
              </thead>
              <tbody>
                {soldes.map((s) => (
                  <tr key={s.leave_type_id} className="border-t border-line">
                    <td className="py-3 font-black">{nomsTypes[s.leave_type_id]}</td>
                    <td className="py-3 text-right">{s.acquired + s.adjustment}</td>
                    <td className="py-3 text-right">{s.taken}</td>
                    <td className="py-3 text-right text-ink-muted">{s.pending}</td>
                    <td className="py-3 text-right font-black text-primary">{s.remaining}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Carte>

        <Carte titre="Absences de l'équipe — ce mois et le suivant">
          {equipe.length === 0 ? (
            <p className="text-sm text-ink-muted">Personne n'est absent sur la période.</p>
          ) : (
            <ul className="flex flex-col gap-2">
              {equipe.map((a, i) => (
                <li key={i} className="flex justify-between gap-3 text-sm flex-wrap">
                  <span className="font-black">{a.full_name}</span>
                  <span className="text-ink-muted">
                    {a.leave_type} · {jour(a.start_date)} → {jour(a.end_date)} ({a.days} j)
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Carte>
      </div>

      <Carte titre="Mes demandes">
        {mesDemandes.length === 0 ? (
          <p className="text-sm text-ink-muted">Aucune demande déposée.</p>
        ) : (
          <ul className="flex flex-col gap-3">
            {mesDemandes.map((d) => (
              <li
                key={d.id}
                className="flex items-center justify-between gap-4 bg-input rounded-2xl px-5 py-4 text-sm flex-wrap"
              >
                <div className="flex items-center gap-3 flex-wrap min-w-0">
                  <Badge statut={d.status} />
                  <span className="font-black">{nomsTypes[d.leave_type_id]}</span>
                  <span className="text-ink-muted">
                    du {jour(d.start_date)} au {jour(d.end_date)} · {d.days} j
                  </span>
                </div>
                {['pending', 'approved'].includes(d.status) && (
                  <button
                    onClick={() => annuler(d.id)}
                    className="text-[10px] font-black uppercase tracking-widest text-ink-muted hover:text-danger"
                  >
                    Annuler
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </Carte>
    </div>
  )
}
