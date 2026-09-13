import React, { useState, useEffect, useMemo } from 'react'
import axios from 'axios'
import {
  API_BASE,
  closePeriod,
  getMailConfig,
  getPrefs,
  getTimesheet,
  messageErreur,
  patchPrefs,
  testDigest,
} from './api/client'
import { BlocConges, DemandeCongeModal } from './pages/Conges'
import { Tickets } from './pages/Tickets'
import { BilanGlobal } from './pages/BilanGlobal'
import { useConges } from './hooks/useConges'
import {
  format, startOfMonth, endOfMonth, eachDayOfInterval,
  isSameMonth, isSameDay, addMonths, subMonths,
  getDay, parseISO, getDate
} from 'date-fns'
import { fr } from 'date-fns/locale'
import {
  ChevronDown, ChevronLeft, ChevronRight, Briefcase, Calendar, Info, Plus,
  Trash2, Save, AlertCircle, CheckCircle2, Loader2, User, LogOut, Lock, Key, Settings, Eye, EyeOff, Users, Layout, BarChart3,
  Mail, Moon, Sun
} from 'lucide-react'

function App() {
  const [currentUser, setCurrentUser] = useState(() => {
    const saved = localStorage.getItem('scopa_user')
    const token = localStorage.getItem('scopa_token')
    // Une session sans jeton ne sert a rien : toutes les routes la refuseraient.
    return saved && token ? JSON.parse(saved) : null
  })

  const [currentDate, setCurrentDate] = useState(new Date())
  const [currentView, setCurrentView] = useState(currentUser ? 'cra' : 'login')
  const [projects, setProjects] = useState([])
  const [userProjects, setUserProjects] = useState([])
  const [allUsers, setAllUsers] = useState([])
  const [craEntries, setCraEntries] = useState([])
  const [loading, setLoading] = useState(false)
  const [saveStatus, setSaveStatus] = useState(null)

  // Spreadsheet grid states
  const [activeRows, setActiveRows] = useState([])
  const [gridData, setGridData] = useState({})
  const [draftCell, setDraftCell] = useState({ key: null, date: null, value: "" })

  // Admin states
  const [selectedReviewUser, setSelectedReviewUser] = useState(null)

  // Forms
  const [loginForm, setLoginForm] = useState({ username: '', password: '' })
  const [showPassword, setShowPassword] = useState(false)
  const [theme, setTheme] = useState(() => localStorage.getItem('scopa_theme') || 'light')
  const [prefs, setPrefs] = useState(null)
  // Sous 768 px, le tableau mensuel de 1500 px n'est pas manipulable : on
  // affiche une semaine à la fois, avec de gros boutons de demi-journée.
  const [semaineMobile, setSemaineMobile] = useState(0)
  const [demandeOuverte, setDemandeOuverte] = useState(false)
  const [mailConfig, setMailConfig] = useState(null)
  const [mailStatus, setMailStatus] = useState(null)
  const [passForm, setPassForm] = useState({ old: '', new: '', confirm: '' })
  const [projectNameInput, setProjectNameInput] = useState("")
  const [projectCategoryInput, setProjectCategoryInput] = useState("Mission")
  const [editingProject, setEditingProject] = useState(null)
  const [editingUser, setEditingUser] = useState(null)
  const [userForm, setUserForm] = useState({ fullName: '', username: '', email: '', isAdmin: false, password: '' })
  const [errorMsg, setErrorMsg] = useState("")

  useEffect(() => {
    if (currentUser) {
      if (currentUser.is_admin) {
        fetchProjects();
        fetchAllUsers();
      }
      fetchUserProjects();
      fetchCRA();
    }
  }, [currentUser, currentDate]);

  useEffect(() => {
    if (currentUser?.is_admin && currentView === 'admin_cra' && selectedReviewUser) {
      const refreshAdminSelection = async () => {
        const uid = selectedReviewUser.id;
        const year = currentDate.getFullYear();
        const month = currentDate.getMonth() + 1;
        try {
          const res = await axios.get(`${API_BASE}/cra/${uid}/${year}/${month}`);
          setSelectedReviewUser(prev => ({ ...prev, entries: res.data }));
        } catch (err) { console.error("Error refreshing admin review", err) }
      };
      refreshAdminSelection();
    }
  }, [currentDate, currentView]);

  const fetchProjects = async () => {
    try {
      const res = await axios.get(`${API_BASE}/projects/`);
      setProjects(res.data);
    } catch (err) { console.error("Error projects", err) }
  };

  const fetchUserProjects = async () => {
    if (!currentUser) return;
    try {
      const res = await axios.get(`${API_BASE}/users/${currentUser.id}/projects`);
      setUserProjects(res.data);
    } catch (err) { console.error("Error user projects", err) }
  };

  const fetchAllUsers = async () => {
    if (!currentUser?.is_admin) return;
    try {
      const res = await axios.get(`${API_BASE}/users/`);
      setAllUsers(res.data);
    } catch (err) { console.error("Error users", err) }
  };

  const fetchCRA = async (userId = null) => {
    const uid = userId || currentUser?.id;
    if (!uid) return;
    setLoading(true);
    try {
      const year = currentDate.getFullYear();
      const month = currentDate.getMonth() + 1;
      const res = await axios.get(`${API_BASE}/cra/${uid}/${year}/${month}`);
      const entries = res.data;

      if (!userId) { // If it's the current user's CRA
        setCraEntries(entries);
        const rows = [];
        const data = {};
        entries.forEach(e => {
          const rowKey = e.project_id ? `P-${e.project_id}` : `A-${e.activity_type}`;
          if (!rows.find(r => r.key === rowKey)) {
            rows.push({
              key: rowKey,
              project_id: e.project_id,
              activity_type: e.activity_type
            });
          }
          if (!data[rowKey]) data[rowKey] = {};
          data[rowKey][format(parseISO(e.date), 'yyyy-MM-dd')] = e.duration_factor;
        });
        setActiveRows(rows);
        setGridData(data);
      } else {
        return entries; // Return for admin view
      }
    } catch (err) { console.error("Error CRA", err) }
    finally { setLoading(false); }
  };

  // Congés : chargés avec le CRA, puisqu'ils s'affichent sous le calendrier.
  const conges = useConges(currentUser ?? { id: 0, is_admin: false })

  // Préférences de notification, chargées à l'ouverture de l'onglet profil.
  useEffect(() => {
    if (!currentUser || currentView !== 'profile') return
    getPrefs().then(setPrefs).catch(() => setPrefs(null))
    if (currentUser.is_admin) {
      getMailConfig().then(setMailConfig).catch(() => setMailConfig(null))
    }
  }, [currentUser, currentView])

  const basculerPref = async (champ) => {
    const precedent = prefs
    const suivant = { ...prefs, [champ]: !prefs[champ] }
    setPrefs(suivant)
    try {
      setPrefs(await patchPrefs({
        daily_digest: suivant.daily_digest,
        closing_reminder: suivant.closing_reminder,
      }))
    } catch (err) {
      setPrefs(precedent)
      setErrorMsg(messageErreur(err, "La préférence n'a pas été enregistrée"))
    }
  }

  const envoyerEssai = async () => {
    setMailStatus('Envoi…')
    try {
      const r = await testDigest()
      setMailStatus(
        r.status === 'sent'
          ? `Envoyé à ${r.to}`
          : r.status === 'dry_run'
            ? "Essai à blanc : rien n'a été envoyé"
            : 'Envoi désactivé (MAIL_ENABLED)',
      )
    } catch (err) {
      setMailStatus(messageErreur(err, "L'envoi a échoué"))
    }
  }

  // Le theme se pose sur <html> : les tokens de theme.css basculent d'un bloc.
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    localStorage.setItem('scopa_theme', theme)
  }, [theme])

  const handleLogin = async (e) => {
    e.preventDefault();
    setLoading(true);
    setErrorMsg("");
    try {
      const res = await axios.post(`${API_BASE}/auth/login`, loginForm);
      localStorage.setItem('scopa_token', res.data.access_token);
      localStorage.setItem('scopa_user', JSON.stringify(res.data));
      setCurrentUser(res.data);
      setCurrentView('cra');
    } catch (err) {
      setErrorMsg(err.response?.data?.detail || "Erreur de connexion");
    } finally { setLoading(false); }
  };

  const handleLogout = () => {
    localStorage.removeItem('scopa_token');
    localStorage.removeItem('scopa_user');
    setCurrentUser(null);
    setCurrentView('login');
  };

  const handlePassChange = async (e) => {
    e.preventDefault();
    if (passForm.new !== passForm.confirm) {
      setErrorMsg("Les mots de passe ne correspondent pas");
      return;
    }
    setLoading(true);
    setErrorMsg("");
    try {
      await axios.post(`${API_BASE}/users/password`, {
        user_id: currentUser.id,
        old_password: passForm.old,
        new_password: passForm.new
      });
      setSaveStatus('success');
      setPassForm({ old: '', new: '', confirm: '' });
      setTimeout(() => setSaveStatus(null), 3000);
    } catch (err) {
      setErrorMsg(err.response?.data?.detail || "Erreur de mot de passe");
    } finally { setLoading(false); }
  };

  const updateCell = (rowKey, dateStr, value) => {
    const val = value === "" ? 0 : parseFloat(value);
    setGridData(prev => ({
      ...prev,
      [rowKey]: {
        ...(prev[rowKey] || {}),
        [dateStr]: val
      }
    }));
  };

  const addRow = (type, projectId = null) => {
    const rowKey = projectId ? `P-${projectId}` : `A-${type}`;
    if (activeRows.find(r => r.key === rowKey)) return;
    setActiveRows([...activeRows, { key: rowKey, project_id: projectId, activity_type: type }]);
    setGridData(prev => ({ ...prev, [rowKey]: {} }));
  };

  const removeRow = (rowKey) => {
    setActiveRows(activeRows.filter(r => r.key !== rowKey));
    const newData = { ...gridData };
    delete newData[rowKey];
    setGridData(newData);
  };

  const saveCRA = async () => {
    setLoading(true);
    try {
      const payload = [];
      activeRows.forEach(row => {
        const rowData = gridData[row.key] || {};
        Object.entries(rowData).forEach(([date, val]) => {
          if (val > 0) {
            payload.push({
              date,
              duration_factor: val,
              activity_type: row.activity_type,
              user_id: currentUser.id,
              project_id: row.project_id
            });
          }
        });
      });
      await axios.post(`${API_BASE}/cra/batch`, payload);
      setSaveStatus('success');
      setTimeout(() => setSaveStatus(null), 3000);
      fetchCRA();
    } catch (err) { console.error(err); setSaveStatus('error'); }
    finally { setLoading(false); }
  };

  const daysInMonth = useMemo(() => {
    return eachDayOfInterval({
      start: startOfMonth(currentDate),
      end: endOfMonth(currentDate)
    });
  }, [currentDate]);

  const getDayTotal = (dateStr) => {
    let total = 0;
    activeRows.forEach(row => { total += (gridData[row.key]?.[dateStr] || 0); });
    return total;
  };

  // Metadonnees du mois : feries, absences approuvees, cloture, trous.
  // Un seul aller-retour, la ou l'ecran devrait croiser quatre sources.
  const [meta, setMeta] = useState(null)
  const [metaBusy, setMetaBusy] = useState(false)
  const period = format(currentDate, 'yyyy-MM')

  const chargerMeta = async () => {
    if (!currentUser) return
    try {
      setMeta(await getTimesheet(period, currentUser.id))
    } catch (err) {
      setMeta(null)
    }
  }

  useEffect(() => { chargerMeta() }, [period, currentUser?.id])

  const feriesDuMois = useMemo(() => new Set(meta?.holidays ?? []), [meta])
  const chargeAbsences = meta?.leave_load ?? {}

  const cloturerLeMois = async () => {
    setMetaBusy(true)
    setErrorMsg('')
    try {
      await closePeriod(period)
      await chargerMeta()
    } catch (err) {
      setErrorMsg(messageErreur(err, "Le mois n'a pas pu etre cloture"))
      await chargerMeta()
    } finally {
      setMetaBusy(false)
    }
  }

  const monthStats = useMemo(() => {
    const workingDays = daysInMonth.filter(d => getDay(d) !== 0 && getDay(d) !== 6).length;
    let totalEntered = 0;
    Object.values(gridData).forEach(row => {
      Object.values(row).forEach(val => {
        totalEntered += (val || 0);
      });
    });
    return { workingDays, totalEntered };
  }, [daysInMonth, gridData]);

  const renderHeader = () => (
    <header className="bg-card border-b-2 border-line p-4 md:p-6 flex flex-col md:flex-row md:items-center md:justify-between gap-3 md:gap-4 sticky top-0 z-50">
      <div className="flex items-center gap-3 shrink-0">
        <div className="bg-primary w-10 h-10 md:w-12 md:h-12 rounded-lg flex items-center justify-center -rotate-2 shrink-0">
          <span className="text-on-primary font-black text-xl md:text-2xl">S</span>
        </div>
        <div className="cursor-pointer" onClick={() => currentUser && setCurrentView('cra')}>
          <h1 className="text-2xl font-black leading-tight tracking-tighter">SCOPA</h1>
          <p className="text-[10px] font-bold text-ink-muted tracking-widest uppercase">Les artisans de la donnée</p>
        </div>
      </div>

      {currentUser && (
        <div className="flex flex-col-reverse md:flex-row md:items-center gap-3 md:gap-8 min-w-0">
          <nav className="flex items-center gap-4 md:gap-6 font-black text-xs tracking-widest uppercase overflow-x-auto custom-scrollbar min-w-0">
            <button onClick={() => setCurrentView('cra')} className={`transition-all whitespace-nowrap ${currentView === 'cra' ? 'text-primary' : 'opacity-30'}`}>Mon CRA</button>
            <button onClick={() => setCurrentView('tickets')} className={`transition-all whitespace-nowrap ${currentView === 'tickets' ? 'text-primary' : 'opacity-30'}`}>Tickets</button>
            {currentUser.is_admin && (
              <>
                <button onClick={() => setCurrentView('admin_cra')} className={`transition-all whitespace-nowrap ${currentView === 'admin_cra' ? 'text-primary' : 'opacity-30'}`}>Revues CRA</button>
                <button onClick={() => setCurrentView('admin_global')} className={`transition-all whitespace-nowrap ${currentView === 'admin_global' ? 'text-primary' : 'opacity-30'}`}>Bilan Global</button>
                <button onClick={() => setCurrentView('projects')} className={`transition-all whitespace-nowrap ${currentView === 'projects' ? 'text-primary' : 'opacity-30'}`}>Projets</button>
                <button onClick={() => setCurrentView('admin_users')} className={`transition-all whitespace-nowrap ${currentView === 'admin_users' ? 'text-primary' : 'opacity-30'}`}>Collaborateurs</button>
              </>
            )}
          </nav>
          <div className="md:border-l md:pl-6 flex items-center gap-3 shrink-0 self-end md:self-auto">
            <div onClick={() => setCurrentView('profile')} className={`cursor-pointer group flex items-center gap-2 px-3 py-1 rounded-xl transition-all ${currentView === 'profile' ? 'bg-inverse text-on-inverse' : 'hover:bg-hovered'}`}>
              <p className="text-[10px] font-black uppercase leading-none">{currentUser.full_name}</p>
              <User size={14} />
            </div>
            <button
              onClick={() => setTheme(t => (t === 'dark' ? 'light' : 'dark'))}
              aria-label={theme === 'dark' ? 'Passer en thème clair' : 'Passer en thème sombre'}
              style={{ background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--text-muted)', display: 'flex' }}
            >
              {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
            </button>
            <button onClick={handleLogout} className="text-ink-subtle hover:text-danger"><LogOut size={16} /></button>
          </div>
        </div>
      )}
    </header>
  );

  // Reprise de la mise en page du login Plouf (plouf_front/src/pages/Login.jsx) :
  // illustration du perroquet en fond, panneau flou a gauche, carte de connexion.
  // La mecanique d'authentification est inchangee : meme handleLogin, meme endpoint.
  const renderLogin = () => (
    <main className="login-page">
      <section className="login-panel">
        <div className="login-card">
          <div style={{ marginBottom: '2rem', textAlign: 'center' }}>
            <img
              src="/logo/scopa.png"
              alt="SCOPA"
              style={{ margin: '0 auto 1rem', height: '56px', objectFit: 'contain', display: 'block' }}
            />
            <h1 style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--text-main)', marginBottom: '0.25rem' }}>
              Connexion
            </h1>
            <p style={{ fontSize: '0.875rem', color: 'var(--text-muted)' }}>
              Entrez vos identifiants pour accéder au CRA SCOPA
            </p>
          </div>

          {errorMsg && (
            <div role="alert" className="alert-error" style={{ marginBottom: '1rem' }}>
              {errorMsg}
            </div>
          )}

          <form onSubmit={handleLogin} style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
            <div className="form-group">
              <label htmlFor="username">
                Identifiant <span style={{ color: 'var(--danger)' }}>*</span>
              </label>
              <input
                id="username"
                type="text"
                className="form-input"
                value={loginForm.username}
                onChange={e => setLoginForm({ ...loginForm, username: e.target.value })}
                required
                autoComplete="username"
                placeholder="gconstant"
              />
            </div>

            <div className="form-group">
              <label htmlFor="password">
                Mot de passe <span style={{ color: 'var(--danger)' }}>*</span>
              </label>
              <div style={{ position: 'relative' }}>
                <input
                  id="password"
                  type={showPassword ? 'text' : 'password'}
                  className="form-input"
                  style={{ paddingRight: '3rem' }}
                  value={loginForm.password}
                  onChange={e => setLoginForm({ ...loginForm, password: e.target.value })}
                  required
                  autoComplete="current-password"
                  placeholder="••••••••"
                />
                <button
                  type="button"
                  aria-label={showPassword ? 'Masquer le mot de passe' : 'Afficher le mot de passe'}
                  onClick={() => setShowPassword(v => !v)}
                  style={{
                    position: 'absolute', right: '0.75rem', top: '50%', transform: 'translateY(-50%)',
                    background: 'transparent', border: 'none', cursor: 'pointer', padding: '0.25rem',
                    color: 'var(--text-muted)', display: 'flex', alignItems: 'center',
                  }}
                >
                  {showPassword ? <Eye size={18} /> : <EyeOff size={18} />}
                </button>
              </div>
            </div>

            <button
              type="submit"
              className="btn-primary"
              disabled={loading}
              style={{ marginTop: '0.5rem', width: '100%', borderRadius: '9999px' }}
            >
              {loading ? 'Connexion…' : 'Se connecter'}
            </button>
          </form>
        </div>
      </section>
    </main>
  );

  const renderBandeauMois = () => {
    if (!meta) return null
    const trous = meta.missing_days ?? []
    const surcharges = Object.entries(meta.overloaded_days ?? {})

    return (
      <div className="flex flex-col gap-3 mb-8">
        {meta.closed && (
          <div className="bg-primary-soft border-2 border-primary rounded-2xl px-6 py-4 text-sm font-black uppercase tracking-widest text-primary">
            Mois clôturé — lecture seule. Un administrateur peut le rouvrir.
          </div>
        )}
        {!meta.closed && trous.length > 0 && (
          <div role="status" className="bg-card border-2 border-warning rounded-2xl px-6 py-4 text-sm">
            <span className="font-black uppercase tracking-widest text-warning">
              {trous.length} jour{trous.length > 1 ? 's' : ''} ouvré{trous.length > 1 ? 's' : ''} sans saisie ni absence
            </span>
            <span className="text-ink-muted"> — {trous.map(j => j.slice(8)).join(', ')}</span>
          </div>
        )}
        {surcharges.length > 0 && (
          <div className="text-xs text-ink-muted">
            Journées à plus d'une unité : {surcharges.map(([j, v]) => `${j.slice(8)} (${v})`).join(', ')}
          </div>
        )}
      </div>
    )
  }

  const renderSemaineMobile = () => {
    const ouvres = daysInMonth.filter(d => getDay(d) !== 0 && getDay(d) !== 6)
    const semaines = []
    for (let i = 0; i < ouvres.length; i += 5) semaines.push(ouvres.slice(i, i + 5))
    if (semaines.length === 0) return null

    const index = Math.min(semaineMobile, semaines.length - 1)
    const semaine = semaines[index]
    const verrouille = meta?.closed

    return (
      <div className="md:hidden flex flex-col gap-4">
        <div className="flex items-center justify-between bg-card rounded-2xl p-2 border border-line">
          <button
            onClick={() => setSemaineMobile(Math.max(0, index - 1))}
            disabled={index === 0}
            aria-label="Semaine précédente"
            className="p-3 rounded-xl disabled:opacity-30"
          >
            <ChevronLeft size={18} />
          </button>
          <span className="font-black text-[10px] uppercase tracking-widest">
            Semaine {index + 1} / {semaines.length}
          </span>
          <button
            onClick={() => setSemaineMobile(Math.min(semaines.length - 1, index + 1))}
            disabled={index === semaines.length - 1}
            aria-label="Semaine suivante"
            className="p-3 rounded-xl disabled:opacity-30"
          >
            <ChevronRight size={18} />
          </button>
        </div>

        {activeRows.length === 0 && (
          <p className="text-sm text-ink-muted px-2">
            Ajoute un projet ou une activité pour commencer à saisir.
          </p>
        )}

        {semaine.map(jour => {
          const dateStr = format(jour, 'yyyy-MM-dd')
          const ferie = feriesDuMois.has(dateStr)
          const absent = (chargeAbsences[dateStr] ?? 0) >= 1
          const total = activeRows.reduce(
            (s, r) => s + (gridData[r.key]?.[dateStr] || 0), 0,
          )

          return (
            <section key={dateStr} className="bg-card rounded-[20px] border-2 border-line p-4">
              <header className="flex items-center justify-between mb-3">
                <h3 className="font-black text-sm uppercase tracking-widest">
                  {format(jour, 'EEEE d', { locale: fr })}
                </h3>
                {ferie ? (
                  <span className="text-[10px] font-black uppercase tracking-widest text-ink-muted">Férié</span>
                ) : absent ? (
                  <span className="text-[10px] font-black uppercase tracking-widest text-primary">Absent</span>
                ) : (
                  <span className="text-[10px] font-black tracking-widest text-ink-muted">
                    {total.toFixed(1)}
                  </span>
                )}
              </header>

              {!ferie && !absent && activeRows.map(row => {
                const valeur = gridData[row.key]?.[dateStr] || 0
                const nom = row.project_id
                  ? (projects.find(p => p.id === row.project_id)?.name || row.activity_type)
                  : row.activity_type
                return (
                  <div key={row.key} className="flex items-center justify-between gap-3 py-2 border-t border-line first:border-0">
                    <span className="text-xs font-black truncate flex-1">{nom}</span>
                    <div className="flex gap-1 shrink-0">
                      {[0, 0.5, 1].map(v => (
                        <button
                          key={v}
                          disabled={verrouille}
                          onClick={() => updateCell(row.key, dateStr, v === 0 ? "" : String(v))}
                          className={`min-w-[44px] min-h-[44px] rounded-xl text-xs font-black border-2 transition-all disabled:opacity-40 ${
                            valeur === v
                              ? 'bg-primary text-on-primary border-primary'
                              : 'border-line text-ink-muted'
                          }`}
                        >
                          {v === 0 ? '—' : v === 0.5 ? '½' : '1'}
                        </button>
                      ))}
                    </div>
                  </div>
                )
              })}
            </section>
          )
        })}
      </div>
    )
  }

  const renderSpreadsheet = () => (
    <main className="p-8 w-full">
      <div className="max-w-[100vw] mx-auto">
        <div className="mb-10">
          <h2 className="text-5xl font-black uppercase tracking-tighter mb-4">Mon activité</h2>

          {/* Une seule rangee d'actions : elle defile horizontalement plutot
              que de passer a la ligne, pour garder Sauvegarder a cote du reste. */}
          <div className="flex items-center gap-2 flex-nowrap overflow-x-auto custom-scrollbar pb-2">
            <div className="flex items-center bg-card rounded-2xl p-2 shadow-sm border border-line shrink-0">
              <button onClick={() => setCurrentDate(subMonths(currentDate, 1))} className="hover:bg-hovered p-2 rounded-xl transition-all"><ChevronLeft size={18} /></button>
              <span className="px-4 font-black text-xs uppercase tracking-widest min-w-[150px] text-center">{format(currentDate, 'MMMM yyyy', { locale: fr })}</span>
              <button onClick={() => setCurrentDate(addMonths(currentDate, 1))} className="hover:bg-hovered p-2 rounded-xl transition-all"><ChevronRight size={18} /></button>
            </div>

            <div className="relative shrink-0">
              <select
                onChange={(e) => {
                  const pid = e.target.value; if (!pid) return;
                  const p = (currentUser.is_admin ? projects : userProjects).find(proj => proj.id === parseInt(pid));
                  addRow(p.category, p.id); e.target.value = "";
                }}
                className="appearance-none w-[220px] truncate bg-card border-2 border-line rounded-2xl pl-6 pr-11 py-3 font-black uppercase text-[10px] tracking-widest cursor-pointer hover:border-primary transition-all"
                style={{ fontFamily: 'var(--font-sans)' }}
              >
                <option value="">+ Ajouter un projet</option>
                {(currentUser.is_admin ? projects : userProjects).map(p => <option key={p.id} value={p.id}>{p.name} ({p.category})</option>)}
              </select>
              <ChevronDown
                size={14}
                className="absolute right-4 top-1/2 -translate-y-1/2 pointer-events-none text-ink-muted"
              />
            </div>

            <button onClick={() => addRow('Absence')} className="shrink-0 bg-card border-2 border-line rounded-2xl px-6 py-3 font-black uppercase text-[10px] tracking-widest hover:border-danger transition-all">+ Absence</button>
            <button onClick={() => addRow('Formation')} className="shrink-0 bg-card border-2 border-line rounded-2xl px-6 py-3 font-black uppercase text-[10px] tracking-widest hover:border-warning transition-all">+ Formation</button>
            <button onClick={() => addRow('Férié')} className="shrink-0 bg-card border-2 border-line rounded-2xl px-6 py-3 font-black uppercase text-[10px] tracking-widest hover:border-success transition-all">+ Férié</button>

            <button
              type="button"
              onClick={() => setDemandeOuverte(true)}
              className="shrink-0 bg-card border-2 border-line rounded-2xl px-6 py-3 font-black uppercase text-[10px] tracking-widest hover:border-primary transition-all"
            >
              Demander un congé
            </button>

            <button
              type="button"
              onClick={cloturerLeMois}
              disabled={metaBusy || meta?.closed}
              className="shrink-0 bg-card border-2 border-line rounded-2xl px-6 py-3 font-black uppercase text-[10px] tracking-widest hover:border-primary transition-all disabled:opacity-40"
            >
              {meta?.closed ? 'Mois clôturé' : 'Clôturer le mois'}
            </button>

            <button
              onClick={saveCRA}
              disabled={loading || meta?.closed}
              className={`shrink-0 ml-auto flex items-center gap-2 px-8 py-3 rounded-2xl font-black uppercase text-[10px] tracking-widest transition-all shadow-lg disabled:opacity-40 ${saveStatus === 'success' ? 'bg-success text-on-primary' : 'bg-primary text-on-primary hover:scale-105'}`}
            >
              {loading ? <Loader2 className="animate-spin" size={16} /> : (saveStatus === 'success' ? <CheckCircle2 size={16} /> : <Save size={16} />)}
              {saveStatus === 'success' ? 'Enregistré' : 'Sauvegarder'}
            </button>
          </div>

          <div className="flex items-center gap-2 mt-3 max-w-[420px]">
            <div className="h-1.5 flex-1 bg-track rounded-full overflow-hidden">
              <div
                className="h-full bg-primary transition-all duration-500"
                style={{ width: `${Math.min(100, (monthStats.totalEntered / monthStats.workingDays) * 100)}%` }}
              ></div>
            </div>
            <span className="text-[10px] font-black uppercase tracking-widest text-ink-muted whitespace-nowrap">
              {monthStats.totalEntered.toFixed(1)} / {monthStats.workingDays} UNITÉS
            </span>
          </div>
        </div>

        {renderBandeauMois()}

        {renderSemaineMobile()}

        <div className="hidden md:block bg-card rounded-[40px] shadow-2xl border border-line overflow-x-auto custom-scrollbar">
          <table className="w-full border-collapse min-w-[1500px]">
            <thead>
              <tr className="bg-input">
                <th className="sticky left-0 z-20 bg-input p-6 text-left border-b-2 border-line min-w-[300px] shadow-[4px_0_10px_-5px_rgba(0,0,0,0.05)] text-[10px] font-black uppercase text-ink-muted">Projets / Activités</th>
                {daysInMonth.map(day => {
                  const dateStr = format(day, 'yyyy-MM-dd');
                  const ferie = feriesDuMois.has(dateStr);
                  const nonOuvre = getDay(day) === 0 || getDay(day) === 6 || ferie;
                  return (
                    <th
                      key={dateStr}
                      title={ferie ? 'Jour férié' : undefined}
                      className={`p-4 border-b-2 border-line min-w-[50px] ${nonOuvre ? 'bg-hovered opacity-40' : ''}`}
                    >
                      <div className="flex flex-col items-center">
                        <span className="text-[10px] font-black uppercase tracking-tighter mb-1">{format(day, 'EEE', { locale: fr })}</span>
                        <span className="text-lg font-black">{format(day, 'd')}</span>
                      </div>
                    </th>
                  );
                })}
                <th className="p-6 border-b-2 border-line font-black text-[10px] uppercase text-ink-muted">Total</th>
              </tr>
            </thead>
            <tbody>
              {activeRows.map(row => {
                let totalRow = 0;
                return (
                  <tr key={row.key} className="hover:bg-input transition-all border-b border-line group text-sm font-black uppercase">
                    <td className="sticky left-0 z-10 bg-card p-6 shadow-[4px_0_10px_-5px_rgba(0,0,0,0.05)] group-hover:bg-input">
                      <div className="flex items-center justify-between">
                        <span>{row.project_id ? (projects.find(p => p.id === row.project_id)?.name || userProjects.find(p => p.id === row.project_id)?.name || 'Projet') : row.activity_type}</span>
                        <button onClick={() => removeRow(row.key)} className="text-ink-subtle group-hover:text-danger"><Trash2 size={14} /></button>
                      </div>
                    </td>
                    {daysInMonth.map(day => {
                      const dateStr = format(day, 'yyyy-MM-dd');
                      const val = gridData[row.key]?.[dateStr] || 0;
                      if (val > 0) totalRow += val;
                      const ferie = feriesDuMois.has(dateStr);
                      const weekend = getDay(day) === 0 || getDay(day) === 6;
                      // Journee entierement couverte par une absence approuvee :
                      // il n'y a plus rien a imputer dessus.
                      const absent = (chargeAbsences[dateStr] ?? 0) >= 1;
                      const verrouille = meta?.closed || absent;
                      return (
                        <td
                          key={dateStr}
                          title={absent ? 'Absence approuvée' : (ferie ? 'Jour férié' : undefined)}
                          className={`p-2 border-r border-line ${weekend || ferie ? 'bg-input opacity-30 grayscale' : ''} ${absent ? 'bg-primary-soft' : ''}`}
                        >
                          {!weekend && !ferie && absent && (
                            <div className="text-center text-[10px] font-black uppercase tracking-widest text-primary">
                              Absent
                            </div>
                          )}
                          {!weekend && !ferie && !absent && (
                            <input
                              type="text"
                              readOnly={verrouille}
                              value={draftCell.key === row.key && draftCell.date === dateStr ? draftCell.value : (val || "")}
                              placeholder="0"
                              onFocus={() => setDraftCell({ key: row.key, date: dateStr, value: val || "" })}
                              onChange={(e) => {
                                const v = e.target.value.replace(',', '.');
                                if (v === "" || /^\d*\.?\d*$/.test(v)) setDraftCell({ key: row.key, date: dateStr, value: v });
                              }}
                              onBlur={() => {
                                const v = draftCell.key === row.key && draftCell.date === dateStr ? draftCell.value : "";
                                updateCell(row.key, dateStr, v === "" ? "" : v);
                                setDraftCell({ key: null, date: null, value: "" });
                              }}
                              className={`w-full h-12 text-center font-black rounded-xl outline-none transition-all ${val > 0 ? 'bg-primary text-on-primary' : 'bg-transparent hover:bg-hovered'}`}
                            />
                          )}
                        </td>
                      );
                    })}
                    <td className="p-6 text-center bg-input">{totalRow.toFixed(1)}</td>
                  </tr>
                );
              })}
            </tbody>
            <tfoot>
              <tr className="bg-hovered text-[10px] font-black uppercase">
                <td className="p-6 text-right sticky left-0 z-10 bg-track shadow-[4px_0_10px_-5px_rgba(0,0,0,0.05)]">Charge Totale</td>
                {daysInMonth.map(day => {
                  const total = getDayTotal(format(day, 'yyyy-MM-dd'));
                  return (
                    <td key={format(day, 'yyyy-MM-dd')} className={`p-4 text-center ${getDay(day) === 0 || getDay(day) === 6 ? 'opacity-20' : ''}`}>
                      {getDay(day) !== 0 && getDay(day) !== 6 && (
                        <div className={`px-2 py-1 rounded-lg ${total > 1 ? 'bg-interne text-on-primary' : total === 1 ? 'text-primary' : 'text-ink-muted'}`}>{total.toFixed(1)}</div>
                      )}
                    </td>
                  );
                })}
                <td className="bg-track"></td>
              </tr>
            </tfoot>
          </table>
        </div>

        {/* Les congés vivent sous le calendrier : poser une absence et
            remplir son CRA sont le même geste. */}
        <BlocConges conges={conges} currentUser={currentUser} />
      </div>

      {demandeOuverte && (
        <DemandeCongeModal conges={conges} onFermer={() => setDemandeOuverte(false)} />
      )}
    </main>
  );

  const renderAdminCRAView = () => (
    <main className="p-8 max-w-7xl mx-auto">
      <h2 className="text-5xl font-black uppercase tracking-tighter mb-10">Revues CRA</h2>
      <div className="grid grid-cols-4 gap-4 mb-10">
        {allUsers.filter(u => !u.is_admin).map(u => (
          <div
            key={u.id}
            onClick={async () => {
              const entries = await fetchCRA(u.id);
              setSelectedReviewUser({ ...u, entries });
            }}
            className={`bg-card p-6 rounded-3xl border-2 transition-all cursor-pointer hover:scale-[1.02] ${selectedReviewUser?.id === u.id ? 'border-primary' : 'border-transparent shadow-sm'}`}
          >
            <p className="text-xs font-black uppercase">{u.full_name}</p>
            <p className="text-[10px] text-ink-muted font-bold uppercase tracking-widest leading-none mt-1">@{u.username}</p>
          </div>
        ))}
      </div>

      {selectedReviewUser && (
        <div className="bg-card rounded-[40px] p-10 border-2 border-line-strong animate-in slide-in-from-bottom-5 duration-500 shadow-2xl">
          <div className="flex justify-between items-center mb-10">
            <h3 className="text-3xl font-black uppercase tracking-tighter">Fiche de {selectedReviewUser.full_name}</h3>
            <div className="flex items-center bg-primary-soft rounded-2xl p-1 border border-primary-soft shadow-sm transition-all hover:bg-primary-soft">
              <button onClick={() => setCurrentDate(subMonths(currentDate, 1))} className="hover:bg-primary-soft p-2 rounded-xl transition-all text-primary"><ChevronLeft size={16} /></button>
              <span className="px-6 font-black text-xs uppercase tracking-widest text-primary min-w-[150px] text-center">{format(currentDate, 'MMMM yyyy', { locale: fr })}</span>
              <button onClick={() => setCurrentDate(addMonths(currentDate, 1))} className="hover:bg-primary-soft p-2 rounded-xl transition-all text-primary"><ChevronRight size={16} /></button>
            </div>
          </div>

          <div className="grid grid-cols-3 gap-6 mb-12">
            {[
              { label: 'Missions', type: 'Mission', color: 'bg-formation', icon: Briefcase },
              { label: 'Formations', type: 'Formation', color: 'bg-interne', icon: Calendar },
              { label: 'Interne', type: 'Interne', color: 'bg-mission', icon: Layout },
              { label: 'Absences', type: 'Absence', color: 'bg-danger', icon: AlertCircle },
              { label: 'Fériés', type: 'Férié', color: 'bg-success', icon: Calendar },
            ].map(stat => {
              const total = selectedReviewUser.entries
                .filter(e => e.activity_type === stat.type)
                .reduce((sum, e) => sum + e.duration_factor, 0);
              return (
                <div key={stat.type} className="bg-input rounded-3xl p-6 border-2 border-transparent hover:border-line transition-all">
                  <div className="flex items-center gap-4 mb-2">
                    <div className={`${stat.color} p-2 rounded-xl text-on-primary`}><stat.icon size={18} /></div>
                    <span className="text-[10px] font-black uppercase tracking-widest text-ink-muted">{stat.label}</span>
                  </div>
                  <div className="flex items-baseline gap-2">
                    <span className="text-4xl font-black tracking-tighter">{total.toFixed(1)}</span>
                    <span className="text-xs font-bold text-ink-muted uppercase tracking-widest text-right w-full">Jours</span>
                  </div>
                </div>
              );
            })}
          </div>

          <div className="overflow-x-auto custom-scrollbar">
            <table className="w-full border-collapse text-[10px] font-black uppercase min-w-[1000px]">
              <thead>
                <tr className="bg-input border-b border-line">
                  <th className="p-4 text-left min-w-[150px]">Activité</th>
                  {daysInMonth.map(d => (
                    <th key={format(d, 'd')} className={`p-2 w-8 ${getDay(d) === 0 || getDay(d) === 6 ? 'opacity-20' : ''}`}>{format(d, 'd')}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {/* Unique activities in this month's results for this user */}
                {Array.from(new Set(selectedReviewUser.entries.map(e => e.project_id ? `P-${e.project_id}` : `A-${e.activity_type}`))).map(rowKey => {
                  const entry = selectedReviewUser.entries.find(e => (e.project_id ? `P-${e.project_id}` : `A-${e.activity_type}`) === rowKey);
                  const projectName = entry?.project_id ? projects.find(p => p.id === entry.project_id)?.name : null;
                  const activityType = entry?.activity_type;
                  return (
                    <tr key={rowKey} className="border-b border-line">
                      <td className="p-4">{projectName || activityType}</td>
                      {daysInMonth.map(day => {
                        const entry = selectedReviewUser.entries.find(e => isSameDay(parseISO(e.date), day) && (e.project_id ? `P-${e.project_id}` : `A-${e.activity_type}`) === rowKey);
                        return (
                          <td key={format(day, 'd')} className={`p-2 text-center text-[8px] ${getDay(day) === 0 || getDay(day) === 6 ? 'opacity-20' : ''}`}>
                            {entry ? <span className="bg-primary text-on-primary px-1.5 py-0.5 rounded-sm">{entry.duration_factor}</span> : '-'}
                          </td>
                        )
                      })}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </main>
  );

  const renderAdminUsersView = () => (
    <main className="p-12 max-w-5xl mx-auto">
      <h2 className="text-5xl font-black uppercase tracking-tighter mb-10">
        {editingUser ? 'Modifier le Collaborateur' : 'Gestion Collaborateurs'}
      </h2>

      <div className="bg-card rounded-[40px] p-10 border-2 border-line-strong shadow-2xl mb-12">
        <form onSubmit={async (e) => {
          e.preventDefault();
          const payload = {
            full_name: userForm.fullName,
            username: userForm.username,
            email: userForm.email,
            is_admin: userForm.isAdmin,
            password: userForm.password || undefined
          };
          try {
            if (editingUser) {
              await axios.put(`${API_BASE}/users/${editingUser.id}`, payload);
            } else {
              await axios.post(`${API_BASE}/users/`, payload);
            }
            setUserForm({ fullName: '', username: '', email: '', isAdmin: false, password: '' });
            setEditingUser(null);
            fetchAllUsers();
          } catch (err) {
            setErrorMsg(err.response?.data?.detail || "Erreur lors de l'enregistrement");
          }
        }} className="space-y-6">
          <div className="grid grid-cols-2 gap-4">
            <input type="text" value={userForm.fullName} onChange={e => setUserForm({ ...userForm, fullName: e.target.value })} placeholder="NOM COMPLET" className="bg-input border-2 border-transparent focus:border-primary p-5 rounded-2xl outline-none font-black text-sm uppercase" />
            <input type="text" value={userForm.username} onChange={e => setUserForm({ ...userForm, username: e.target.value })} placeholder="NOM D'UTILISATEUR" className="bg-input border-2 border-transparent focus:border-primary p-5 rounded-2xl outline-none font-black text-sm uppercase" />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <input type="email" value={userForm.email} onChange={e => setUserForm({ ...userForm, email: e.target.value })} placeholder="EMAIL" className="bg-input border-2 border-transparent focus:border-primary p-5 rounded-2xl outline-none font-black text-sm uppercase" />
            <input type="password" value={userForm.password} onChange={e => setUserForm({ ...userForm, password: e.target.value })} placeholder={editingUser ? "NOUVEAU MOT DE PASSE (OPTIONNEL)" : "MOT DE PASSE"} className="bg-input border-2 border-transparent focus:border-primary p-5 rounded-2xl outline-none font-black text-sm uppercase" />
          </div>
          <div className="flex items-center gap-4">
            <label className="flex items-center gap-3 cursor-pointer">
              <input type="checkbox" checked={userForm.isAdmin} onChange={e => setUserForm({ ...userForm, isAdmin: e.target.checked })} className="w-5 h-5 accent-[var(--primary)]" />
              <span className="text-xs font-black uppercase text-ink-muted">Droits Administrateur</span>
            </label>
            <div className="flex-1"></div>
            {editingUser && (
              <button type="button" onClick={() => { setEditingUser(null); setUserForm({ fullName: '', username: '', email: '', isAdmin: false, password: '' }); }} className="bg-hovered text-ink px-8 py-4 rounded-2xl font-black uppercase text-xs">Annuler</button>
            )}
            <button type="submit" className="bg-primary text-on-primary px-10 py-4 rounded-2xl font-black uppercase text-xs">
              {editingUser ? 'Enregistrer' : 'Créer le collaborateur'}
            </button>
          </div>
        </form>
      </div>

      <div className="grid gap-6">
        {allUsers.map(u => (
          <div key={u.id} className={`bg-card p-10 rounded-[40px] shadow-sm border-2 transition-all ${editingUser?.id === u.id ? 'border-primary' : 'border-line'}`}>
            <div className="flex justify-between items-start mb-10">
              <div>
                <div className="flex items-center gap-3">
                  <h4 className="text-2xl font-black uppercase tracking-tighter">{u.full_name}</h4>
                  {u.is_admin && <span className="bg-inverse text-on-inverse text-[8px] px-2 py-0.5 rounded-full font-black uppercase tracking-widest">ADMIN</span>}
                </div>
                <p className="text-xs text-ink-muted font-black tracking-widest mt-1">@{u.username} • {u.email}</p>
              </div>
              <button
                onClick={() => {
                  setEditingUser(u);
                  setUserForm({ fullName: u.full_name, username: u.username, email: u.email, isAdmin: u.is_admin, password: '' });
                }}
                className="p-3 bg-input rounded-xl hover:bg-hovered transition-all text-ink-muted hover:text-ink"
              >
                <Settings size={18} />
              </button>
            </div>

            <div>
              <h5 className="text-[10px] font-black uppercase tracking-widest mb-6 text-ink-muted">Projets Associés</h5>
              <div className="grid grid-cols-3 gap-4">
                {projects.map(p => {
                  const isAssigned = (u.projects || []).some(up => up.id === p.id);
                  return (
                    <label key={p.id} className={`flex items-center gap-3 p-4 bg-input rounded-2xl cursor-pointer hover:bg-hovered transition-all border-2 ${isAssigned ? 'border-primary' : 'border-transparent'}`}>
                      <input
                        type="checkbox"
                        className="hidden"
                        checked={isAssigned}
                        onChange={async (e) => {
                          const checked = e.target.checked;
                          const currentIds = (u.projects || []).map(up => up.id);
                          const newIds = checked
                            ? [...currentIds, p.id]
                            : currentIds.filter(id => id !== p.id);

                          try {
                            setLoading(true);
                            await axios.post(`${API_BASE}/users/${u.id}/projects`, { project_ids: newIds });
                            await fetchAllUsers();
                            // Also refresh current user projects if they are the one being edited
                            if (u.id === currentUser.id) await fetchUserProjects();
                          } catch (err) {
                            console.error("Assignment error:", err);
                            setErrorMsg("Erreur lors de l'assignation");
                          } finally {
                            setLoading(false);
                          }
                        }}
                      />
                      <Briefcase size={14} className={isAssigned ? "text-primary" : "text-ink-subtle"} />
                      <span className="text-[10px] font-black uppercase text-ink">{p.name}</span>
                    </label>
                  )
                })}
              </div>
            </div>
          </div>
        ))}
      </div>
    </main>
  );

  const renderProjectsView = () => (
    <main className="max-w-4xl mx-auto p-12">
      <h2 className="text-5xl font-black uppercase tracking-tighter mb-10">
        {editingProject ? 'Modifier le projet' : 'Gestion Projets'}
      </h2>
      <div className="bg-card rounded-[40px] p-10 border-2 border-line-strong shadow-2xl mb-12">
        <form onSubmit={async (e) => {
          e.preventDefault(); if (!projectNameInput) return;
          if (editingProject) {
            await axios.put(`${API_BASE}/projects/${editingProject.id}`, { name: projectNameInput.toUpperCase(), category: projectCategoryInput });
          } else {
            await axios.post(`${API_BASE}/projects/`, { name: projectNameInput.toUpperCase(), category: projectCategoryInput });
          }
          setProjectNameInput("");
          setEditingProject(null);
          fetchProjects();
        }} className="space-y-6">
          <input type="text" value={projectNameInput} onChange={e => setProjectNameInput(e.target.value)} placeholder="NOM DU PROJET" className="w-full bg-input border-2 border-transparent focus:border-primary p-5 rounded-3xl outline-none font-black text-sm uppercase" />
          <div className="flex gap-4">
            {['Mission', 'Formation', 'Interne'].map(cat => <button key={cat} type="button" onClick={() => setProjectCategoryInput(cat)} className={`flex-1 py-4 rounded-2xl font-black uppercase text-xs border-2 transition-all ${projectCategoryInput === cat ? 'bg-inverse text-on-inverse border-line-strong' : 'border-line text-ink-muted'}`}>{cat}</button>)}
          </div>
          <div className="flex gap-4">
            <button type="submit" className="flex-1 bg-primary text-on-primary p-6 rounded-3xl font-black uppercase text-sm">
              {editingProject ? 'Enregistrer les modifications' : 'Créer le projet'}
            </button>
            {editingProject && (
              <>
                <button
                  type="button"
                  onClick={() => { setEditingProject(null); setProjectNameInput(""); }}
                  className="bg-hovered text-ink p-6 rounded-3xl font-black uppercase text-sm"
                >
                  Annuler
                </button>
                <button
                  type="button"
                  onClick={async () => {
                    if (!window.confirm(`Supprimer le projet "${editingProject.name}" ?`)) return;
                    await axios.delete(`${API_BASE}/projects/${editingProject.id}`);
                    setEditingProject(null);
                    setProjectNameInput("");
                    fetchProjects();
                  }}
                  className="bg-danger text-on-primary p-6 rounded-3xl font-black uppercase text-sm hover:bg-danger-hover transition-all"
                >
                  Supprimer
                </button>
              </>
            )}
          </div>
        </form>
      </div>
      <div className="grid gap-3">
        {projects.map(p => (
          <div
            key={p.id}
            onClick={() => {
              setEditingProject(p);
              setProjectNameInput(p.name);
              setProjectCategoryInput(p.category);
            }}
            className={`bg-card p-6 rounded-3xl border-2 flex items-center justify-between shadow-sm cursor-pointer transition-all ${editingProject?.id === p.id ? 'border-primary' : 'border-line hover:border-line-hover'}`}
          >
            <div className="flex items-center gap-4">
              <div className={`w-2 h-2 rounded-full ${p.category === 'Mission' ? 'bg-primary' : p.category === 'Interne' ? 'bg-mission' : 'bg-interne'}`}></div>
              <span className="font-black uppercase text-sm">{p.name}</span>
            </div>
            <div className="flex items-center gap-4">
              <span className="text-[10px] font-black text-ink-muted uppercase tracking-widest">{p.category}</span>
              <Settings size={14} className="text-ink-subtle" />
            </div>
          </div>
        ))}
      </div>
    </main>
  );

  const renderProfile = () => (
    <main className="max-w-xl mx-auto p-12">
      <div className="bg-card rounded-[50px] p-16 shadow-2xl border-2 border-line-strong">
        <div className="text-center mb-10"><h2 className="text-4xl font-black uppercase tracking-tighter">{currentUser.full_name}</h2></div>
        <h3 className="text-xl font-black uppercase mb-6 flex items-center gap-3"><Mail size={20} /> Notifications</h3>
        {prefs && (
          <div className="mb-10 flex flex-col gap-3">
            {[
              ['daily_digest', 'Récap matinal', "Du lundi au vendredi, s'il y a quelque chose à signaler"],
              ['closing_reminder', 'Rappel de clôture', "En fin de mois, si le CRA n'est pas clôturé"],
            ].map(([champ, titre, aide]) => (
              <label key={champ} className="flex items-start gap-4 bg-input rounded-2xl p-5 cursor-pointer">
                <input
                  type="checkbox"
                  checked={prefs[champ]}
                  onChange={() => basculerPref(champ)}
                  className="w-5 h-5 mt-0.5 accent-[var(--primary)]"
                />
                <span>
                  <span className="block text-sm font-black">{titre}</span>
                  <span className="block text-xs text-ink-muted mt-1 normal-case">{aide}</span>
                </span>
              </label>
            ))}
          </div>
        )}

        {currentUser.is_admin && mailConfig && (
          <div className="mb-10 bg-input rounded-2xl p-5 text-xs">
            <p className="font-black uppercase tracking-widest text-ink-muted mb-2">Serveur d'envoi</p>
            <p className="text-ink-muted normal-case">
              {mailConfig.host || '— aucun hôte —'} · {mailConfig.sender}
            </p>
            <p className="mt-2 normal-case">
              {!mailConfig.enabled
                ? 'Envoi désactivé'
                : mailConfig.dry_run
                  ? 'Essai à blanc : les messages sont construits mais pas envoyés'
                  : 'Envoi actif'}
              {mailConfig.missing.length > 0 && (
                <span className="text-danger"> — manque {mailConfig.missing.join(', ')}</span>
              )}
            </p>
            <button
              type="button"
              onClick={envoyerEssai}
              className="mt-4 px-5 py-2 rounded-2xl border-2 border-line font-black uppercase text-[10px] tracking-widest hover:border-primary"
            >
              M'envoyer un essai
            </button>
            {mailStatus && <p className="mt-2 text-ink-muted normal-case">{mailStatus}</p>}
          </div>
        )}

        <h3 className="text-xl font-black uppercase mb-8 flex items-center gap-3"><Lock size={20} /> Sécurité</h3>
        <form onSubmit={handlePassChange} className="space-y-6">
          <div className="space-y-2"><label className="text-[10px] font-black text-ink-muted tracking-widest uppercase ml-4">Ancien mot de passe</label><input type="password" value={passForm.old} onChange={e => setPassForm({ ...passForm, old: e.target.value })} className="w-full bg-input border-2 border-transparent focus:border-primary p-5 rounded-2xl outline-none font-black text-sm" /></div>
          <div className="space-y-2"><label className="text-[10px] font-black text-ink-muted tracking-widest uppercase ml-4">Nouveau mot de passe</label><input type="password" value={passForm.new} onChange={e => setPassForm({ ...passForm, new: e.target.value })} className="w-full bg-input border-2 border-transparent focus:border-primary p-5 rounded-2xl outline-none font-black text-sm" /></div>
          <div className="space-y-2"><label className="text-[10px] font-black text-ink-muted tracking-widest uppercase ml-4">Confirmer</label><input type="password" value={passForm.confirm} onChange={e => setPassForm({ ...passForm, confirm: e.target.value })} className="w-full bg-input border-2 border-transparent focus:border-primary p-5 rounded-2xl outline-none font-black text-sm" /></div>
          <button type="submit" disabled={loading} className="w-full bg-primary text-on-primary p-6 rounded-2xl font-black uppercase text-sm flex items-center justify-center gap-3">
            {saveStatus === 'success' ? <CheckCircle2 size={20} /> : <Key size={18} />} {saveStatus === 'success' ? 'C\'est fait !' : 'Mettre à jour'}
          </button>
        </form>
      </div>
    </main>
  );

  // Page pleine : ni en-tete ni navigation tant qu'on n'est pas connecte.
  if (!currentUser) return renderLogin();

  return (
    <div
      className="min-h-screen"
      style={{ backgroundColor: 'var(--bg-main)', color: 'var(--text-main)', fontFamily: 'var(--font-sans)' }}
    >
      {renderHeader()}
      {currentUser && currentView === 'cra' && renderSpreadsheet()}
      {currentUser && currentView === 'tickets' && <Tickets currentUser={currentUser} />}
      {currentUser && currentView === 'projects' && renderProjectsView()}
      {currentUser && currentView === 'admin_cra' && renderAdminCRAView()}
      {currentUser && currentUser.is_admin && currentView === 'admin_global' && <BilanGlobal />}
      {currentUser && currentView === 'admin_users' && renderAdminUsersView()}
      {currentUser && currentView === 'profile' && renderProfile()}
    </div>
  )
}

export default App
