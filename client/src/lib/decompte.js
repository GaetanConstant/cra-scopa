/*
 * Décompte d'une demande de congé, pour l'affichage en direct dans le
 * formulaire.
 *
 * Le serveur reste la seule autorité : il recalcule à la création et c'est sa
 * valeur qui est enregistrée. Ce module existe pour que l'utilisateur voie le
 * nombre de jours avant d'envoyer, pas pour le décider.
 * Miroir de server/leaves.py — toute correction là-bas se répercute ici.
 */

const MOITIES = ['am', 'pm']

/** Jours ouvrés de la plage : lundi à vendredi, fériés retirés. */
export function joursOuvres(debut, fin, feries) {
  const exclus = new Set(feries)
  const jours = []
  const courant = new Date(debut)
  const borne = new Date(fin)
  while (courant <= borne) {
    const iso = courant.toISOString().slice(0, 10)
    const jourSemaine = courant.getUTCDay()
    if (jourSemaine !== 0 && jourSemaine !== 6 && !exclus.has(iso)) jours.push(iso)
    courant.setUTCDate(courant.getUTCDate() + 1)
  }
  return jours
}

/**
 * Nombre de jours décomptés, ou `null` si la saisie est incohérente.
 * `debutMoitie` et `finMoitie` valent 'am', 'pm' ou une valeur vide.
 */
export function compterJours(debut, fin, feries, debutMoitie, finMoitie) {
  if (!debut || !fin || fin < debut) return null

  const ouvres = joursOuvres(debut, fin, feries)
  if (ouvres.length === 0) return 0

  const d = debutMoitie || 'am'
  const f = finMoitie || 'pm'

  if (debut === fin) {
    const demies = MOITIES.indexOf(f) - MOITIES.indexOf(d) + 1
    return demies > 0 ? demies / 2 : null
  }

  let demies = 2 * ouvres.length
  if (d === 'pm' && ouvres.includes(debut)) demies -= 1
  if (f === 'am' && ouvres.includes(fin)) demies -= 1
  return demies / 2
}
