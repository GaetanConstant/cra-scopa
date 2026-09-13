/*
 * Couche d'accès à l'API : une fonction par endpoint, aucun appel axios
 * ailleurs dans les composants.
 *
 * L'URL de base et les intercepteurs (jeton, déconnexion sur 401) sont posés
 * ici une fois pour toutes.
 */

import axios from 'axios'

export const API_BASE = window.location.host.includes(':3300')
  ? window.location.origin.replace(':3300', ':5500')
  : (window.location.host.includes(':3000')
    ? window.location.origin.replace(':3000', ':5500')
    : (window.location.port ? window.location.origin.replace(`:${window.location.port}`, ':5500') : `${window.location.origin}/api`))

// Toute requête porte le jeton délivré au login.
axios.interceptors.request.use((config) => {
  const token = localStorage.getItem('scopa_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// Jeton absent, invalide ou expiré : on vide la session et on repart du login,
// plutôt que de laisser l'écran se remplir d'erreurs silencieuses.
axios.interceptors.response.use(
  (response) => response,
  (error) => {
    const isLoginCall = error.config?.url?.endsWith('/auth/login')
    if (error.response?.status === 401 && !isLoginCall) {
      localStorage.removeItem('scopa_token')
      localStorage.removeItem('scopa_user')
      window.location.reload()
    }
    return Promise.reject(error)
  },
)

const get = (chemin, params) => axios.get(`${API_BASE}${chemin}`, { params }).then((r) => r.data)
const post = (chemin, corps) => axios.post(`${API_BASE}${chemin}`, corps).then((r) => r.data)
const put = (chemin, corps) => axios.put(`${API_BASE}${chemin}`, corps).then((r) => r.data)
const patch = (chemin, corps) => axios.patch(`${API_BASE}${chemin}`, corps).then((r) => r.data)
const del = (chemin) => axios.delete(`${API_BASE}${chemin}`).then((r) => r.data)

/**
 * Message d'erreur lisible pour l'utilisateur.
 * FastAPI renvoie `detail` en chaîne, ou en objet pour les erreurs riches
 * (la clôture y met la liste des jours manquants).
 */
export function messageErreur(error, defaut = 'Une erreur est survenue') {
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (detail?.message) return detail.message
  return defaut
}

export function joursManquants(error) {
  return error?.response?.data?.detail?.missing_days ?? []
}

// --- Congés ----------------------------------------------------------------

export const getLeaveTypes = () => get('/leaves/types')
export const getLeaves = (params) => get('/leaves', params)
export const createLeave = (corps) => post('/leaves', corps)
export const decideLeave = (id, approve, comment) => post(`/leaves/${id}/decide`, { approve, comment })
export const cancelLeave = (id) => post(`/leaves/${id}/cancel`)
export const getBalances = (year) => get('/leaves/balances', { year })
export const putBalance = (corps) => put('/leaves/balances', corps)
export const getTeamCalendar = (from_date, to_date) => get('/leaves/team-calendar', { from_date, to_date })

// --- Temps -----------------------------------------------------------------

export const getTimesheet = (period, user_id) => get('/time', { period, user_id })
export const closePeriod = (period, user_id) => post('/time/close', { period, user_id })
export const reopenPeriod = (period, user_id) => post('/time/reopen', { period, user_id })
export const copyWeek = (target_week_start, user_id) => post('/time/copy-week', { target_week_start, user_id })

// --- Référentiel -----------------------------------------------------------

export const getHolidays = (year) => get('/holidays', { year })
export const getUsers = () => get('/users/')

// --- Tickets ---------------------------------------------------------------

export const getBoard = (params) => get('/tickets/board', params)
export const getTicket = (id) => get(`/tickets/${id}`)
export const createTicket = (corps) => post('/tickets', corps)
export const patchTicket = (id, corps) => patch(`/tickets/${id}`, corps)
export const moveTicket = (id, corps) => post(`/tickets/${id}/move`, corps)
export const deleteTicket = (id) => del(`/tickets/${id}`)
export const addComment = (id, body) => post(`/tickets/${id}/comments`, { body })
export const getTags = () => get('/tickets/tags')
export const createTag = (corps) => post('/tickets/tags', corps)
export const getProjects = () => get('/projects/')

// --- Activité --------------------------------------------------------------

export const getActivity = (from_date, to_date) =>
  get('/reporting/activity', { from_date, to_date })
export const exportActivity = (from_date, to_date) =>
  get('/reporting/activity/export', { from_date, to_date })

// --- Notifications ---------------------------------------------------------

export const getPrefs = () => get('/notifications/prefs')
export const patchPrefs = (corps) => patch('/notifications/prefs', corps)
export const getMailConfig = () => get('/notifications/config')
export const testDigest = () => post('/notifications/digest/test')
