import React, { useEffect, useMemo, useState } from 'react'
import { format, startOfMonth, endOfMonth, subMonths } from 'date-fns'
import { fr } from 'date-fns/locale'
import { AlertCircle, Download, Loader2 } from 'lucide-react'

import { exportActivity, getActivity, messageErreur } from '../api/client'

const iso = (d) => format(d, 'yyyy-MM-dd')

// Natures d'activité affichées en colonnes, reprises de l'ancien bilan global.
const TYPES = [
  { id: 'Mission', label: 'Missions', couleur: 'bg-mission' },
  { id: 'Formation', label: 'Formations', couleur: 'bg-formation' },
  { id: 'Interne', label: 'Interne', couleur: 'bg-interne' },
  { id: 'Absence', label: 'Absences', couleur: 'bg-danger' },
  { id: 'Férié', label: 'Fériés', couleur: 'bg-success' },
]

/** Périodes proposées : le mois courant, le précédent, l'année en cours. */
function periodes() {
  const maintenant = new Date()
  const moisDernier = subMonths(maintenant, 1)
  return [
    {
      id: 'mois',
      label: format(maintenant, 'MMMM yyyy', { locale: fr }),
      from: iso(startOfMonth(maintenant)),
      to: iso(endOfMonth(maintenant)),
    },
    {
      id: 'precedent',
      label: format(moisDernier, 'MMMM yyyy', { locale: fr }),
      from: iso(startOfMonth(moisDernier)),
      to: iso(endOfMonth(moisDernier)),
    },
    {
      id: 'annee',
      label: `Année ${maintenant.getFullYear()}`,
      from: `${maintenant.getFullYear()}-01-01`,
      to: `${maintenant.getFullYear()}-12-31`,
    },
  ]
}

function Taux({ valeur }) {
  if (valeur === null || valeur === undefined) {
    return <span className="text-ink-subtle" title="Aucun jour disponible">—</span>
  }
  const pourcent = Math.round(valeur * 100)
  // Au-delà de 100 %, plusieurs missions se cumulent sur une même journée.
  const couleur =
    pourcent > 100 ? 'text-warning' : pourcent >= 80 ? 'text-success' : 'text-ink'
  return <span className={`font-black ${couleur}`}>{pourcent} %</span>
}

export function BilanGlobal() {
  const options = useMemo(periodes, [])
  const [periode, setPeriode] = useState(options[0])
  const [donnees, setDonnees] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [deplie, setDeplie] = useState(null)

  useEffect(() => {
    let annule = false
    setLoading(true)
    setError(null)
    getActivity(periode.from, periode.to)
      .then((d) => !annule && setDonnees(d))
      .catch((err) => !annule && setError(messageErreur(err, "Impossible de charger l'activité")))
      .finally(() => !annule && setLoading(false))
    return () => {
      annule = true
    }
  }, [periode])

  const telecharger = async () => {
    // L'export passe par une requête authentifiée : un lien direct partirait
    // sans jeton et se ferait refuser.
    const csv = await exportActivity(periode.from, periode.to)
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }))
    const lien = document.createElement('a')
    lien.href = url
    lien.download = `activite-${periode.from}-${periode.to}.csv`
    lien.click()
    URL.revokeObjectURL(url)
  }

  return (
    <main className="p-8 w-full">
      <h2 className="text-5xl font-black uppercase tracking-tighter mb-6">Bilan global</h2>

      <div className="flex items-center gap-2 flex-wrap mb-8">
        <div className="flex items-center gap-1 bg-input rounded-2xl p-1">
          {options.map((o) => (
            <button
              key={o.id}
              onClick={() => setPeriode(o)}
              className={`px-4 py-2 rounded-xl text-[10px] font-black uppercase tracking-widest transition-all ${
                periode.id === o.id ? 'bg-card text-primary shadow-sm' : 'text-ink-muted'
              }`}
            >
              {o.label}
            </button>
          ))}
        </div>

        <button
          onClick={telecharger}
          disabled={loading || !!error}
          className="flex items-center gap-2 px-5 py-3 rounded-2xl border-2 border-line font-black uppercase text-[10px] tracking-widest hover:border-primary transition-all disabled:opacity-40"
        >
          <Download size={14} /> Export CSV
        </button>
      </div>

      {error && (
        <div role="alert" className="alert-error max-w-2xl">
          <AlertCircle size={18} /> {error}
        </div>
      )}

      {loading && (
        <div className="flex items-center gap-3 text-ink-muted">
          <Loader2 className="animate-spin" size={20} />
          <span className="text-xs font-black uppercase tracking-widest">Calcul en cours…</span>
        </div>
      )}

      {!loading && !error && donnees && (
        <div className="bg-card rounded-[20px] border-2 border-line overflow-x-auto custom-scrollbar">
          <table className="w-full min-w-[860px]">
            <thead>
              <tr className="text-[9px] uppercase tracking-widest text-ink-muted text-left border-b-2 border-line">
                <th className="p-5">Collaborateur</th>
                {TYPES.map((t) => (
                  <th key={t.id} className="p-5 text-right">
                    <span className={`${t.couleur} inline-block w-2 h-2 rounded-full mr-2`} />
                    {t.label}
                  </th>
                ))}
                <th className="p-5 text-right">Jours ouvrés</th>
                <th className="p-5 text-right">Absences</th>
                <th className="p-5 text-right">Disponibles</th>
                <th className="p-5 text-right">Saisis</th>
                <th className="p-5 text-right">Manquants</th>
                <th className="p-5 text-right">Occupation</th>
              </tr>
            </thead>
            <tbody>
              {donnees.rows.map((l) => (
                <React.Fragment key={l.user_id}>
                  <tr
                    onClick={() => setDeplie(deplie === l.user_id ? null : l.user_id)}
                    className="border-b border-line cursor-pointer hover:bg-hovered transition-colors"
                  >
                    <td className="p-5 font-black">{l.full_name}</td>
                    {TYPES.map((t) => (
                      <td key={t.id} className="p-5 text-right text-ink-muted">
                        {l.by_activity[t.id] ?? '—'}
                      </td>
                    ))}
                    <td className="p-5 text-right text-ink-muted">{l.working_days}</td>
                    <td className="p-5 text-right text-ink-muted">{l.leave_days}</td>
                    <td className="p-5 text-right">{l.available_days}</td>
                    <td className="p-5 text-right font-black">{l.entered_days}</td>
                    <td
                      className={`p-5 text-right ${
                        l.missing_days > 0 ? 'text-warning font-black' : 'text-ink-subtle'
                      }`}
                    >
                      {l.missing_days}
                    </td>
                    <td className="p-5 text-right">
                      <Taux valeur={l.occupancy} />
                    </td>
                  </tr>

                  {deplie === l.user_id && (
                    <tr className="border-b border-line">
                      <td colSpan={7 + TYPES.length} className="px-5 pb-5 bg-input">
                        {l.by_project.length === 0 ? (
                          <p className="text-sm text-ink-muted pt-4">
                            Aucune saisie sur la période.
                          </p>
                        ) : (
                          <ul className="pt-4 flex flex-col gap-2">
                            {l.by_project.map((p) => (
                              <li
                                key={p.label}
                                className="flex items-center justify-between gap-4 text-sm"
                              >
                                <span className="font-black">{p.label}</span>
                                <div className="flex items-center gap-3 flex-1 max-w-[60%]">
                                  <div className="h-1.5 flex-1 bg-track rounded-full overflow-hidden">
                                    <div
                                      className="h-full bg-primary"
                                      style={{
                                        width: `${Math.min(
                                          100,
                                          (p.days / Math.max(l.entered_days, 1)) * 100,
                                        )}%`,
                                      }}
                                    />
                                  </div>
                                  <span className="w-12 text-right font-black">{p.days}</span>
                                </div>
                              </li>
                            ))}
                          </ul>
                        )}
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="text-xs text-ink-muted mt-4">
        Cliquer sur une ligne détaille la répartition par projet. Une occupation
        au-dessus de 100 % signale des journées portant plusieurs missions.
      </p>
    </main>
  )
}
