/*
 * Chargement, filtres et déplacements du kanban.
 *
 * Le déplacement est optimiste : la colonne bouge tout de suite à l'écran,
 * et l'état d'avant est conservé pour être remis si le serveur refuse. Sans
 * ça, une carte reste figée sous le curseur le temps de l'aller-retour.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { getBoard, getTags, getUsers, messageErreur, moveTicket } from '../api/client'

export const COLONNES = [
  { id: 'todo', label: 'À faire' },
  { id: 'in_progress', label: 'En cours' },
  { id: 'to_validate', label: 'À valider' },
  { id: 'done', label: 'Terminé' },
]

const BOARD_VIDE = { todo: [], in_progress: [], to_validate: [], done: [] }

export function useTickets() {
  const [board, setBoard] = useState(BOARD_VIDE)
  const [tags, setTags] = useState([])
  const [utilisateurs, setUtilisateurs] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [toast, setToast] = useState(null)
  const [filtres, setFiltres] = useState({ mine: false, tag_id: '', q: '', priority: '' })

  const params = useMemo(() => {
    const p = {}
    if (filtres.mine) p.mine = true
    if (filtres.tag_id) p.tag_id = Number(filtres.tag_id)
    if (filtres.q) p.q = filtres.q
    if (filtres.priority) p.priority = filtres.priority
    return p
  }, [filtres])

  const charger = useCallback(async () => {
    setError(null)
    try {
      const [colonnes, etiquettes, gens] = await Promise.all([
        getBoard(params),
        getTags(),
        getUsers(),
      ])
      setBoard({ ...BOARD_VIDE, ...colonnes })
      setTags(etiquettes)
      setUtilisateurs(gens)
    } catch (err) {
      setError(messageErreur(err, 'Impossible de charger le tableau'))
    } finally {
      setLoading(false)
    }
  }, [params])

  useEffect(() => {
    charger()
  }, [charger])

  const signaler = (message) => {
    setToast(message)
    setTimeout(() => setToast(null), 4000)
  }

  /**
   * Déplace une carte vers `statut`, juste avant `afterId` (fin de colonne si nul).
   * Applique le changement à l'écran, puis le confirme ou le défait.
   */
  const deplacer = async (ticketId, statut, afterId = null) => {
    const avant = board
    const carte = Object.values(board).flat().find((t) => t.id === ticketId)
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

  return {
    board,
    tags,
    utilisateurs,
    loading,
    error,
    toast,
    filtres,
    setFiltres,
    recharger: charger,
    deplacer,
    signaler,
  }
}
