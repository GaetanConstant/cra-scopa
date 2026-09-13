/*
 * Chargement et actions de l'écran Congés.
 *
 * Toute la logique non visuelle vit ici : le composant ne fait que rendre
 * `loading`, `error` et les données.
 */

import { useCallback, useEffect, useState } from 'react'
import {
  cancelLeave,
  createLeave,
  decideLeave,
  getBalances,
  getHolidays,
  getLeaveTypes,
  getLeaves,
  getTeamCalendar,
  getUsers,
  messageErreur,
} from '../api/client'

/** Premier et dernier jour de la fenêtre du calendrier d'équipe : mois courant + suivant. */
function fenetreEquipe(reference = new Date()) {
  const debut = new Date(Date.UTC(reference.getFullYear(), reference.getMonth(), 1))
  const fin = new Date(Date.UTC(reference.getFullYear(), reference.getMonth() + 2, 0))
  return [debut.toISOString().slice(0, 10), fin.toISOString().slice(0, 10)]
}

export function useConges(currentUser) {
  const annee = new Date().getFullYear()

  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [types, setTypes] = useState([])
  const [feries, setFeries] = useState([])
  const [mesDemandes, setMesDemandes] = useState([])
  const [enAttente, setEnAttente] = useState([])
  const [soldes, setSoldes] = useState([])
  const [equipe, setEquipe] = useState([])
  const [utilisateurs, setUtilisateurs] = useState([])

  const charger = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [debut, fin] = fenetreEquipe()
      const [
        typesRecus,
        feriesRecus,
        demandes,
        soldesRecus,
        calendrier,
        gens,
      ] = await Promise.all([
        getLeaveTypes(),
        getHolidays(annee),
        getLeaves({ user_id: currentUser.id }),
        getBalances(annee),
        getTeamCalendar(debut, fin),
        getUsers(),
      ])

      setTypes(typesRecus)
      setFeries(feriesRecus.map((f) => f.date))
      setMesDemandes(demandes)
      setSoldes(soldesRecus.filter((s) => s.user_id === currentUser.id))
      setEquipe(calendrier)
      setUtilisateurs(gens)

      // La file d'attente n'a de sens que pour un administrateur.
      setEnAttente(currentUser.is_admin ? await getLeaves({ status: 'pending' }) : [])
    } catch (err) {
      setError(messageErreur(err, 'Impossible de charger les congés'))
    } finally {
      setLoading(false)
    }
  }, [annee, currentUser.id, currentUser.is_admin])

  useEffect(() => {
    charger()
  }, [charger])

  const deposer = async (corps) => {
    await createLeave(corps)
    await charger()
  }

  const decider = async (id, approuve) => {
    await decideLeave(id, approuve)
    await charger()
  }

  const annuler = async (id) => {
    await cancelLeave(id)
    await charger()
  }

  return {
    annee,
    loading,
    error,
    types,
    feries,
    mesDemandes,
    enAttente,
    soldes,
    equipe,
    utilisateurs,
    recharger: charger,
    deposer,
    decider,
    annuler,
  }
}
