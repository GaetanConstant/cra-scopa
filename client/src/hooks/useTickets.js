/*
 * Chargement, filtres, regroupement et déplacements du kanban.
 *
 * Le tableau se regroupe par statut (les quatre colonnes du flux) ou par
 * étiquette (la catégorie du ticket). Dans les deux cas le geste est le
 * même : glisser une carte d'une colonne à l'autre. Seul l'effet change —
 * un changement de statut d'un côté, un changement d'étiquette de l'autre.
 *
 * Le déplacement est optimiste : la colonne bouge tout de suite à l'écran,
 * et l'état d'avant est conservé pour être remis si le serveur refuse. Sans
 * ça, une carte reste figée sous le curseur le temps de l'aller-retour.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  getBoard,
  getProjects,
  getUserProjects,
  getTags,
  getUsers,
  messageErreur,
  moveTicket,
  patchTicket,
} from '../api/client'

export const STATUTS = [
  { id: 'todo', label: 'À faire' },
  { id: 'in_progress', label: 'En cours' },
  { id: 'to_validate', label: 'À valider' },
  { id: 'done', label: 'Terminé' },
]

// Colonnes des cartes qu'aucune étiquette, ou aucun projet, ne classe.
export const SANS_ETIQUETTE = 'sans-etiquette'
export const SANS_PROJET = 'sans-projet'

export const REGROUPEMENTS = [
  { id: 'status', label: 'Statut' },
  { id: 'tag', label: 'Étiquette' },
  { id: 'project', label: 'Projet' },
]

const BOARD_VIDE = { todo: [], in_progress: [], to_validate: [], done: [] }

export function useTickets(currentUser) {
  const [board, setBoard] = useState(BOARD_VIDE)
  const [tags, setTags] = useState([])
  const [utilisateurs, setUtilisateurs] = useState([])
  const [projets, setProjets] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [toast, setToast] = useState(null)
  const [groupBy, setGroupBy] = useState('status')
  const [filtres, setFiltres] = useState({
    mine: false,
    tag_id: '',
    q: '',
    priority: '',
    project_id: '',
  })

  const params = useMemo(() => {
    const p = {}
    if (filtres.mine) p.mine = true
    if (filtres.tag_id) p.tag_id = Number(filtres.tag_id)
    if (filtres.q) p.q = filtres.q
    if (filtres.priority) p.priority = filtres.priority
    if (filtres.project_id) p.project_id = Number(filtres.project_id)
    return p
  }, [filtres])

  const charger = useCallback(async () => {
    setError(null)
    try {
      const [colonnes, etiquettes, gens, missions] = await Promise.all([
        getBoard(params),
        getTags(),
        getUsers(),
        // Un consultant ne peut rattacher un ticket qu'a ses missions :
        // lui proposer les autres ne ferait que produire des 403.
        currentUser?.is_admin ? getProjects() : getUserProjects(currentUser.id),
      ])
      setBoard({ ...BOARD_VIDE, ...colonnes })
      setTags(etiquettes)
      setUtilisateurs(gens)
      setProjets(missions)
    } catch (err) {
      setError(messageErreur(err, 'Impossible de charger le tableau'))
    } finally {
      setLoading(false)
    }
  }, [params, currentUser?.id, currentUser?.is_admin])

  useEffect(() => {
    charger()
  }, [charger])

  const toutesLesCartes = useMemo(() => Object.values(board).flat(), [board])

  /** Colonnes affichées, selon le regroupement choisi. */
  const colonnes = useMemo(() => {
    if (groupBy === 'status') return STATUTS
    if (groupBy === 'project') {
      // Dix-sept colonnes dont quinze vides ne se lisent pas. On ne montre que
      // les projets qui portent des tickets ; choisir un projet dans le filtre
      // fait apparaître sa colonne, ce qui permet d'y glisser une carte.
      const portes = new Set(toutesLesCartes.map((t) => t.project_id).filter(Boolean))
      if (filtres.project_id) portes.add(Number(filtres.project_id))
      return [
        ...projets
          .filter((p) => portes.has(p.id))
          .map((p) => ({ id: String(p.id), label: p.code || p.name })),
        { id: SANS_PROJET, label: 'Sans projet' },
      ]
    }
    return [
      ...tags.map((t) => ({ id: String(t.id), label: t.name, color: t.color })),
      { id: SANS_ETIQUETTE, label: 'Sans étiquette' },
    ]
  }, [groupBy, tags, projets, toutesLesCartes, filtres.project_id])

  /**
   * Cartes de chaque colonne.
   * En mode étiquette, une carte portant deux étiquettes apparaît dans les
   * deux colonnes : c'est la réalité du classement, la masquer quelque part
   * donnerait un tableau qui ment.
   */
  const cartesDe = useCallback(
    (colonneId) => {
      if (groupBy === 'status') return board[colonneId] ?? []
      if (groupBy === 'project') {
        if (colonneId === SANS_PROJET) {
          return toutesLesCartes.filter((t) => !t.project_id)
        }
        return toutesLesCartes.filter((t) => t.project_id === Number(colonneId))
      }
      if (colonneId === SANS_ETIQUETTE) {
        return toutesLesCartes.filter((t) => t.tag_ids.length === 0)
      }
      return toutesLesCartes.filter((t) => t.tag_ids.includes(Number(colonneId)))
    },
    [board, groupBy, toutesLesCartes],
  )

  const signaler = (message) => {
    setToast(message)
    setTimeout(() => setToast(null), 4000)
  }

  /** Déplacement entre colonnes de statut : la carte change d'étape. */
  const deplacerStatut = async (ticketId, statut, afterId = null) => {
    const avant = board
    const carte = toutesLesCartes.find((t) => t.id === ticketId)
    if (!carte) return

    const optimiste = Object.fromEntries(
      Object.entries(board).map(([col, cartes]) => [
        col,
        cartes.filter((t) => t.id !== ticketId),
      ]),
    )
    const cible = optimiste[statut] ?? []
    const index = afterId ? cible.findIndex((t) => t.id === afterId) : -1
    const place = index >= 0 ? index : cible.length
    optimiste[statut] = [
      ...cible.slice(0, place),
      { ...carte, status: statut },
      ...cible.slice(place),
    ]
    setBoard(optimiste)

    try {
      await moveTicket(ticketId, { status: statut, after_id: afterId })
      await charger()
    } catch (err) {
      setBoard(avant)
      signaler(messageErreur(err, "Le déplacement n'a pas été enregistré"))
    }
  }

  /**
   * Déplacement entre colonnes d'étiquette : la carte change de catégorie.
   * On retire l'étiquette de la colonne de départ et on pose celle d'arrivée,
   * sans toucher aux autres étiquettes du ticket.
   */
  const deplacerEtiquette = async (ticketId, depuis, vers) => {
    if (depuis === vers) return
    const avant = board
    const carte = toutesLesCartes.find((t) => t.id === ticketId)
    if (!carte) return

    let etiquettes = carte.tag_ids
    if (depuis !== SANS_ETIQUETTE) {
      etiquettes = etiquettes.filter((id) => id !== Number(depuis))
    }
    if (vers !== SANS_ETIQUETTE && !etiquettes.includes(Number(vers))) {
      etiquettes = [...etiquettes, Number(vers)]
    }

    setBoard(
      Object.fromEntries(
        Object.entries(board).map(([col, cartes]) => [
          col,
          cartes.map((t) => (t.id === ticketId ? { ...t, tag_ids: etiquettes } : t)),
        ]),
      ),
    )

    try {
      await patchTicket(ticketId, { tag_ids: etiquettes })
      await charger()
    } catch (err) {
      setBoard(avant)
      signaler(messageErreur(err, "Le changement d'étiquette n'a pas été enregistré"))
    }
  }

  /** Déplacement entre colonnes de projet : la carte change de mission. */
  const deplacerProjet = async (ticketId, vers) => {
    const avant = board
    const projectId = vers === SANS_PROJET ? null : Number(vers)

    setBoard(
      Object.fromEntries(
        Object.entries(board).map(([col, cartes]) => [
          col,
          cartes.map((t) => (t.id === ticketId ? { ...t, project_id: projectId } : t)),
        ]),
      ),
    )

    try {
      await patchTicket(ticketId, { project_id: projectId })
      await charger()
    } catch (err) {
      setBoard(avant)
      signaler(messageErreur(err, "Le changement de projet n'a pas été enregistré"))
    }
  }

  return {
    board,
    projets,
    deplacerProjet,
    colonnes,
    cartesDe,
    groupBy,
    setGroupBy,
    tags,
    utilisateurs,
    loading,
    error,
    toast,
    filtres,
    setFiltres,
    recharger: charger,
    deplacerStatut,
    deplacerEtiquette,
    signaler,
  }
}
