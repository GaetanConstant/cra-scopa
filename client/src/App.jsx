import React, { useState, useEffect, useMemo } from 'react'
import axios from 'axios'
import {
  format, startOfMonth, endOfMonth, eachDayOfInterval,
  isSameMonth, isSameDay, addMonths, subMonths,
  getDay, parseISO, getDate
} from 'date-fns'
import { fr } from 'date-fns/locale'
import {
  ChevronLeft, ChevronRight, Briefcase, Calendar, Info, Plus,
  Trash2, Save, AlertCircle, CheckCircle2, Loader2, User, LogOut, Lock, Key, Settings, Eye, Users, Layout, BarChart3
} from 'lucide-react'

const API_BASE = window.location.host.includes(':3300')
  ? window.location.origin.replace(':3300', ':5500')
  : (window.location.host.includes(':3000')
    ? window.location.origin.replace(':3000', ':5500')
    : (window.location.port ? window.location.origin.replace(`:${window.location.port}`, ':5500') : `${window.location.origin}/api`));

function App() {
  const [currentUser, setCurrentUser] = useState(() => {
    const saved = localStorage.getItem('scopa_user')
    return saved ? JSON.parse(saved) : null
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
  const [allCRAData, setAllCRAData] = useState([]) // For admin view

  // Forms
  const [loginForm, setLoginForm] = useState({ username: '', password: '' })
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

  const fetchAllCRAData = async () => {
    if (!currentUser?.is_admin) return;
    setLoading(true);
    try {
      const year = currentDate.getFullYear();
      const month = currentDate.getMonth() + 1;
      const res = await axios.get(`${API_BASE}/cra/all/${year}/${month}`);
      setAllCRAData(res.data);
    } catch (err) { console.error("Error global CRA", err) }
    finally { setLoading(false); }
  };

  useEffect(() => {
    if (currentView === 'admin_global' && currentUser?.is_admin) {
      fetchAllCRAData();
    }
  }, [currentView, currentDate]);

  const handleLogin = async (e) => {
    e.preventDefault();
    setLoading(true);
    setErrorMsg("");
    try {
      const res = await axios.post(`${API_BASE}/auth/login`, loginForm);
      localStorage.setItem('scopa_user', JSON.stringify(res.data));
      setCurrentUser(res.data);
      setCurrentView('cra');
    } catch (err) {
      setErrorMsg(err.response?.data?.detail || "Erreur de connexion");
    } finally { setLoading(false); }
  };

  const handleLogout = () => {
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
    <header className="bg-white border-b-2 border-black/5 p-6 flex items-center justify-between sticky top-0 z-50">
      <div className="flex items-center gap-3">
        <div className="bg-[#6186EA] w-12 h-12 rounded-lg flex items-center justify-center -rotate-2">
          <span className="text-white font-black text-2xl">S</span>
        </div>
        <div className="cursor-pointer" onClick={() => currentUser && setCurrentView('cra')}>
          <h1 className="text-2xl font-black leading-tight tracking-tighter">SCOPA</h1>
          <p className="text-[10px] font-bold text-gray-400 tracking-widest uppercase">Les artisans de la donnée</p>
        </div>
      </div>

      {currentUser && (
        <div className="flex items-center gap-8">
          <nav className="flex items-center gap-6 font-black text-xs tracking-widest uppercase">
            <button onClick={() => setCurrentView('cra')} className={`transition-all ${currentView === 'cra' ? 'text-[#6186EA]' : 'opacity-30'}`}>Mon CRA</button>
            {currentUser.is_admin && (
              <>
                <button onClick={() => setCurrentView('projects')} className={`transition-all ${currentView === 'projects' ? 'text-[#6186EA]' : 'opacity-30'}`}>Projets</button>
                <button onClick={() => setCurrentView('admin_cra')} className={`transition-all ${currentView === 'admin_cra' ? 'text-[#6186EA]' : 'opacity-30'}`}>Revues CRA</button>
                <button onClick={() => setCurrentView('admin_global')} className={`transition-all ${currentView === 'admin_global' ? 'text-[#6186EA]' : 'opacity-30'}`}>Bilan Global</button>
                <button onClick={() => setCurrentView('admin_users')} className={`transition-all ${currentView === 'admin_users' ? 'text-[#6186EA]' : 'opacity-30'}`}>Collaborateurs</button>
              </>
            )}
          </nav>
          <div className="border-l pl-6 flex items-center gap-4">
            <div onClick={() => setCurrentView('profile')} className={`cursor-pointer group flex items-center gap-2 px-3 py-1 rounded-xl transition-all ${currentView === 'profile' ? 'bg-black text-white' : 'hover:bg-gray-100'}`}>
              <p className="text-[10px] font-black uppercase leading-none">{currentUser.full_name}</p>
              <User size={14} />
            </div>
            <button onClick={handleLogout} className="text-gray-300 hover:text-red-500"><LogOut size={16} /></button>
          </div>
        </div>
      )}
    </header>
  );

  const renderLogin = () => (
    <main className="min-h-[80vh] flex items-center justify-center p-8">
      <div className="bg-white rounded-[50px] p-16 w-full max-w-lg shadow-2xl border-2 border-black animate-in fade-in zoom-in duration-500">
        <div className="text-center mb-12">
          <div className="bg-[#6186EA] w-20 h-20 rounded-3x flex items-center justify-center -rotate-3 mx-auto mb-6 shadow-xl"><span className="text-white font-black text-4xl">S</span></div>
          <h2 className="text-4xl font-black uppercase tracking-tighter">Connexion Artisan</h2>
        </div>
        <form onSubmit={handleLogin} className="space-y-6">
          <div className="space-y-2">
            <label className="text-[10px] font-black uppercase text-gray-400 tracking-widest ml-4">Identifiant</label>
            <input type="text" value={loginForm.username} onChange={e => setLoginForm({ ...loginForm, username: e.target.value })} placeholder="gconstant" className="w-full bg-gray-50 border-2 border-transparent focus:border-[#6186EA] p-6 rounded-3xl outline-none font-black text-sm transition-all" />
          </div>
          <div className="space-y-2">
            <label className="text-[10px] font-black uppercase text-gray-400 tracking-widest ml-4">Mot de passe</label>
            <input type="password" value={loginForm.password} onChange={e => setLoginForm({ ...loginForm, password: e.target.value })} placeholder="••••••••" className="w-full bg-gray-50 border-2 border-transparent focus:border-[#6186EA] p-6 rounded-3xl outline-none font-black text-sm transition-all" />
          </div>
          {errorMsg && <p className="text-red-500 text-[10px] font-black uppercase text-center">{errorMsg}</p>}
          <button type="submit" disabled={loading} className="w-full bg-black text-white p-7 rounded-[30px] font-black uppercase tracking-widest text-sm hover:translate-y-[-2px] hover:shadow-2xl transition-all disabled:opacity-50">
            {loading ? <Loader2 className="animate-spin mx-auto" size={24} /> : "Se connecter"}
          </button>
        </form>
      </div>
    </main>
  );

  const renderSpreadsheet = () => (
    <main className="p-8 w-full">
      <div className="max-w-[100vw] mx-auto">
        <div className="flex items-center justify-between mb-10">
          <div>
            <h2 className="text-5xl font-black uppercase tracking-tighter mb-4">Mon activité</h2>
            <div className="flex items-center gap-6">
              <div className="flex flex-col gap-2">
                <div className="flex items-center bg-white rounded-2xl p-2 shadow-sm border border-black/5">
                  <button onClick={() => setCurrentDate(subMonths(currentDate, 1))} className="hover:bg-gray-100 p-2 rounded-xl transition-all"><ChevronLeft size={20} /></button>
                  <span className="px-6 font-black text-sm uppercase tracking-widest min-w-[180px] text-center">{format(currentDate, 'MMMM yyyy', { locale: fr })}</span>
                  <button onClick={() => setCurrentDate(addMonths(currentDate, 1))} className="hover:bg-gray-100 p-2 rounded-xl transition-all"><ChevronRight size={20} /></button>
                </div>
                <div className="px-4 flex items-center gap-2">
                  <div className="h-1.5 flex-1 bg-gray-200 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-[#6186EA] transition-all duration-500"
                      style={{ width: `${Math.min(100, (monthStats.totalEntered / monthStats.workingDays) * 100)}%` }}
                    ></div>
                  </div>
                  <span className="text-[10px] font-black uppercase tracking-widest text-gray-400 whitespace-nowrap">
                    {monthStats.totalEntered.toFixed(1)} / {monthStats.workingDays} UNITÉS
                  </span>
                </div>
              </div>
              <div className="flex gap-2 self-start mt-1">
                <select
                  onChange={(e) => {
                    const pid = e.target.value; if (!pid) return;
                    const p = (currentUser.is_admin ? projects : userProjects).find(proj => proj.id === parseInt(pid));
                    addRow(p.category, p.id); e.target.value = "";
                  }}
                  className="bg-white border-2 border-black/5 rounded-2xl px-6 py-3 font-black uppercase text-[10px] cursor-pointer"
                >
                  <option value="">+ Ajouter un projet</option>
                  {(currentUser.is_admin ? projects : userProjects).map(p => <option key={p.id} value={p.id}>{p.name} ({p.category})</option>)}
                </select>
                <button onClick={() => addRow('Absence')} className="bg-white border-2 border-black/5 rounded-2xl px-6 py-3 font-black uppercase text-[10px] hover:border-red-500 transition-all">+ Absence</button>
                <button onClick={() => addRow('Formation')} className="bg-white border-2 border-black/5 rounded-2xl px-6 py-3 font-black uppercase text-[10px] hover:border-amber-500 transition-all">+ Formation</button>
              </div>
            </div>
          </div>
          <button onClick={saveCRA} disabled={loading} className={`flex items-center gap-3 px-10 py-5 rounded-3xl font-black uppercase text-sm transition-all shadow-xl ${saveStatus === 'success' ? 'bg-green-500 text-white' : 'bg-[#6186EA] text-white hover:scale-105 hover:shadow-2xl'}`}>
            {loading ? <Loader2 className="animate-spin" size={20} /> : (saveStatus === 'success' ? <CheckCircle2 size={20} /> : <Save size={20} />)}
            {saveStatus === 'success' ? 'Enregistré' : 'Sauvegarder'}
          </button>
        </div>

        <div className="bg-white rounded-[40px] shadow-2xl border border-black/5 overflow-x-auto custom-scrollbar">
          <table className="w-full border-collapse min-w-[1500px]">
            <thead>
              <tr className="bg-gray-50/50">
                <th className="sticky left-0 z-20 bg-gray-50 p-6 text-left border-b-2 border-black/5 min-w-[300px] shadow-[4px_0_10px_-5px_rgba(0,0,0,0.05)] text-[10px] font-black uppercase text-gray-400">Projets / Activités</th>
                {daysInMonth.map(day => (
                  <th key={format(day, 'yyyy-MM-dd')} className={`p-4 border-b-2 border-black/5 min-w-[50px] ${getDay(day) === 0 || getDay(day) === 6 ? 'bg-gray-100/50 opacity-40' : ''}`}>
                    <div className="flex flex-col items-center">
                      <span className="text-[10px] font-black uppercase tracking-tighter mb-1">{format(day, 'EEE', { locale: fr })}</span>
                      <span className="text-lg font-black">{format(day, 'd')}</span>
                    </div>
                  </th>
                ))}
                <th className="p-6 border-b-2 border-black/5 font-black text-[10px] uppercase text-gray-400">Total</th>
              </tr>
            </thead>
            <tbody>
              {activeRows.map(row => {
                let totalRow = 0;
                return (
                  <tr key={row.key} className="hover:bg-gray-50/30 transition-all border-b border-black/5 group text-sm font-black uppercase">
                    <td className="sticky left-0 z-10 bg-white p-6 shadow-[4px_0_10px_-5px_rgba(0,0,0,0.05)] group-hover:bg-gray-50 flex items-center justify-between">
                      <span>{row.project_id ? (projects.find(p => p.id === row.project_id)?.name || userProjects.find(p => p.id === row.project_id)?.name || 'Projet') : row.activity_type}</span>
                      <button onClick={() => removeRow(row.key)} className="text-gray-100 group-hover:text-red-500"><Trash2 size={14} /></button>
                    </td>
                    {daysInMonth.map(day => {
                      const dateStr = format(day, 'yyyy-MM-dd');
                      const val = gridData[row.key]?.[dateStr] || 0;
                      if (val > 0) totalRow += val;
                      return (
                        <td key={dateStr} className={`p-2 border-r border-black/5 ${getDay(day) === 0 || getDay(day) === 6 ? 'bg-gray-50/50 opacity-30 grayscale' : ''}`}>
                          {getDay(day) !== 0 && getDay(day) !== 6 && (
                            <input
                              type="text"
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
                              className={`w-full h-12 text-center font-black rounded-xl outline-none transition-all ${val > 0 ? 'bg-[#6186EA] text-white' : 'bg-transparent hover:bg-gray-100'}`}
                            />
                          )}
                        </td>
                      );
                    })}
                    <td className="p-6 text-center bg-gray-50/50">{totalRow.toFixed(1)}</td>
                  </tr>
                );
              })}
            </tbody>
            <tfoot>
              <tr className="bg-black/5 text-[10px] font-black uppercase">
                <td className="p-6 text-right sticky left-0 z-10 bg-gray-200/50 shadow-[4px_0_10px_-5px_rgba(0,0,0,0.05)]">Charge Totale (cible 1.0)</td>
                {daysInMonth.map(day => {
                  const total = getDayTotal(format(day, 'yyyy-MM-dd'));
                  return (
                    <td key={format(day, 'yyyy-MM-dd')} className={`p-4 text-center ${getDay(day) === 0 || getDay(day) === 6 ? 'opacity-20' : ''}`}>
                      {getDay(day) !== 0 && getDay(day) !== 6 && (
                        <div className={`px-2 py-1 rounded-lg ${total > 1 ? 'bg-red-500 text-white animate-bounce' : total === 1 ? 'text-[#6186EA]' : 'text-gray-400'}`}>{total.toFixed(1)}</div>
                      )}
                    </td>
                  );
                })}
                <td className="bg-black/10"></td>
              </tr>
            </tfoot>
          </table>
        </div>
      </div>
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
            className={`bg-white p-6 rounded-3xl border-2 transition-all cursor-pointer hover:scale-[1.02] ${selectedReviewUser?.id === u.id ? 'border-[#6186EA]' : 'border-transparent shadow-sm'}`}
          >
            <p className="text-xs font-black uppercase">{u.full_name}</p>
            <p className="text-[10px] text-gray-400 font-bold uppercase tracking-widest leading-none mt-1">@{u.username}</p>
          </div>
        ))}
      </div>

      {selectedReviewUser && (
        <div className="bg-white rounded-[40px] p-10 border-2 border-black animate-in slide-in-from-bottom-5 duration-500 shadow-2xl">
          <div className="flex justify-between items-center mb-10">
            <h3 className="text-3xl font-black uppercase tracking-tighter">Fiche de {selectedReviewUser.full_name}</h3>
            <div className="flex items-center bg-[#6186EA]/10 rounded-2xl p-1 border border-[#6186EA]/20 shadow-sm transition-all hover:bg-[#6186EA]/15">
              <button onClick={() => setCurrentDate(subMonths(currentDate, 1))} className="hover:bg-[#6186EA]/20 p-2 rounded-xl transition-all text-[#6186EA]"><ChevronLeft size={16} /></button>
              <span className="px-6 font-black text-xs uppercase tracking-widest text-[#6186EA] min-w-[150px] text-center">{format(currentDate, 'MMMM yyyy', { locale: fr })}</span>
              <button onClick={() => setCurrentDate(addMonths(currentDate, 1))} className="hover:bg-[#6186EA]/20 p-2 rounded-xl transition-all text-[#6186EA]"><ChevronRight size={16} /></button>
            </div>
          </div>

          <div className="grid grid-cols-3 gap-6 mb-12">
            {[
              { label: 'Missions', type: 'Mission', color: 'bg-blue-500', icon: Briefcase },
              { label: 'Formations', type: 'Formation', color: 'bg-amber-400', icon: Calendar },
              { label: 'Interne', type: 'Interne', color: 'bg-indigo-500', icon: Layout },
              { label: 'Absences', type: 'Absence', color: 'bg-red-500', icon: AlertCircle },
            ].map(stat => {
              const total = selectedReviewUser.entries
                .filter(e => e.activity_type === stat.type)
                .reduce((sum, e) => sum + e.duration_factor, 0);
              return (
                <div key={stat.type} className="bg-gray-50 rounded-3xl p-6 border-2 border-transparent hover:border-black/5 transition-all">
                  <div className="flex items-center gap-4 mb-2">
                    <div className={`${stat.color} p-2 rounded-xl text-white`}><stat.icon size={18} /></div>
                    <span className="text-[10px] font-black uppercase tracking-widest text-gray-400">{stat.label}</span>
                  </div>
                  <div className="flex items-baseline gap-2">
                    <span className="text-4xl font-black tracking-tighter">{total.toFixed(1)}</span>
                    <span className="text-xs font-bold text-gray-400 uppercase tracking-widest text-right w-full">Jours</span>
                  </div>
                </div>
              );
            })}
          </div>

          <div className="overflow-x-auto custom-scrollbar">
            <table className="w-full border-collapse text-[10px] font-black uppercase min-w-[1000px]">
              <thead>
                <tr className="bg-gray-50 border-b border-black/5">
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
                    <tr key={rowKey} className="border-b border-black/5">
                      <td className="p-4">{projectName || activityType}</td>
                      {daysInMonth.map(day => {
                        const entry = selectedReviewUser.entries.find(e => isSameDay(parseISO(e.date), day) && (e.project_id ? `P-${e.project_id}` : `A-${e.activity_type}`) === rowKey);
                        return (
                          <td key={format(day, 'd')} className={`p-2 text-center text-[8px] ${getDay(day) === 0 || getDay(day) === 6 ? 'opacity-20' : ''}`}>
                            {entry ? <span className="bg-[#6186EA] text-white px-1.5 py-0.5 rounded-sm">{entry.duration_factor}</span> : '-'}
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

  const renderAdminGlobalView = () => (
    <main className="p-8 max-w-7xl mx-auto">
      <div className="flex items-center justify-between mb-10">
        <div>
          <h2 className="text-5xl font-black uppercase tracking-tighter mb-2">Bilan Global</h2>
          <p className="text-[10px] font-black text-gray-400 uppercase tracking-widest">Activité consolidée de l'agence</p>
        </div>
        <div className="flex items-center bg-white rounded-3xl p-2 border-2 border-black/5 shadow-sm">
          <button onClick={() => setCurrentDate(subMonths(currentDate, 1))} className="hover:bg-gray-100 p-3 rounded-2xl transition-all text-black"><ChevronLeft size={20} /></button>
          <span className="px-8 font-black text-sm uppercase tracking-[0.2em] min-w-[200px] text-center">{format(currentDate, 'MMMM yyyy', { locale: fr })}</span>
          <button onClick={() => setCurrentDate(addMonths(currentDate, 1))} className="hover:bg-gray-100 p-3 rounded-2xl transition-all text-black"><ChevronRight size={20} /></button>
        </div>
      </div>

      <div className="bg-white rounded-[40px] shadow-2xl border-2 border-black overflow-hidden animate-in fade-in slide-in-from-bottom-5 duration-700">
        <table className="w-full border-collapse">
          <thead>
            <tr className="bg-black text-white">
              <th className="p-8 text-left text-[10px] font-black uppercase tracking-widest">Collaborateur</th>
              <th className="p-8 text-center text-[10px] font-black uppercase tracking-widest bg-blue-500">Missions</th>
              <th className="p-8 text-center text-[10px] font-black uppercase tracking-widest bg-amber-400">Formations</th>
              <th className="p-8 text-center text-[10px] font-black uppercase tracking-widest bg-indigo-500">Interne</th>
              <th className="p-8 text-center text-[10px] font-black uppercase tracking-widest bg-red-500">Absences</th>
              <th className="p-8 text-center text-[10px] font-black uppercase tracking-widest bg-gray-900 border-l border-white/20">Total Actif</th>
            </tr>
          </thead>
          <tbody className="divide-y-2 divide-gray-50">
            {allUsers.map(user => {
              const userEntries = allCRAData.filter(e => e.user_id === user.id);
              const getSum = (type) => userEntries.filter(e => e.activity_type === type).reduce((s, e) => s + e.duration_factor, 0);
              
              const mission = getSum('Mission');
              const formation = getSum('Formation');
              const interne = getSum('Interne');
              const absence = getSum('Absence');
              const total = mission + formation + interne;

              return (
                <tr key={user.id} className="hover:bg-gray-50/80 transition-all font-black group">
                  <td className="p-8">
                    <div className="flex items-center gap-4">
                      <div className="w-12 h-12 rounded-2xl bg-gray-100 flex items-center justify-center text-gray-400 group-hover:bg-black group-hover:text-white transition-all duration-300">
                        {user.is_admin ? <Lock size={20} className="text-amber-500" /> : <User size={20} />}
                      </div>
                      <div>
                        <div className="flex items-center gap-2">
                          <p className="uppercase text-sm tracking-tight">{user.full_name}</p>
                          {user.is_admin && <span className="bg-black text-white text-[7px] px-1.5 py-0.5 rounded-full">ADMIN</span>}
                        </div>
                        <p className="text-[10px] text-gray-400 font-bold uppercase tracking-widest">@{user.username}</p>
                      </div>
                    </div>
                  </td>
                  <td className="p-8 text-center text-xl tracking-tighter text-blue-600">{mission.toFixed(1)}</td>
                  <td className="p-8 text-center text-xl tracking-tighter text-amber-500">{formation.toFixed(1)}</td>
                  <td className="p-8 text-center text-xl tracking-tighter text-indigo-600">{interne.toFixed(1)}</td>
                  <td className="p-8 text-center text-xl tracking-tighter text-red-500">{absence.toFixed(1)}</td>
                  <td className="p-8 text-center text-xl tracking-tighter bg-gray-50/50 border-l border-gray-100">{total.toFixed(1)}</td>
                </tr>
              );
            })}
          </tbody>
          <tfoot>
            <tr className="bg-gray-50 font-black border-t-4 border-black">
              <td className="p-8 uppercase text-[10px] tracking-widest">Total Agence</td>
              <td className="p-8 text-center text-2xl tracking-tighter">
                {allCRAData.filter(e => e.activity_type === 'Mission').reduce((s, e) => s + e.duration_factor, 0).toFixed(1)}
              </td>
              <td className="p-8 text-center text-2xl tracking-tighter">
                {allCRAData.filter(e => e.activity_type === 'Formation').reduce((s, e) => s + e.duration_factor, 0).toFixed(1)}
              </td>
              <td className="p-8 text-center text-2xl tracking-tighter">
                {allCRAData.filter(e => e.activity_type === 'Interne').reduce((s, e) => s + e.duration_factor, 0).toFixed(1)}
              </td>
              <td className="p-8 text-center text-2xl tracking-tighter">
                {allCRAData.filter(e => e.activity_type === 'Absence').reduce((s, e) => s + e.duration_factor, 0).toFixed(1)}
              </td>
              <td className="p-8 text-center text-2xl bg-black text-white">
                {allCRAData.filter(e => ['Mission', 'Formation', 'Interne'].includes(e.activity_type)).reduce((s, e) => s + e.duration_factor, 0).toFixed(1)}
              </td>
            </tr>
          </tfoot>
        </table>
      </div>
    </main>
  );

  const renderAdminUsersView = () => (
    <main className="p-12 max-w-5xl mx-auto">
      <h2 className="text-5xl font-black uppercase tracking-tighter mb-10">
        {editingUser ? 'Modifier le Collaborateur' : 'Gestion Collaborateurs'}
      </h2>

      <div className="bg-white rounded-[40px] p-10 border-2 border-black shadow-2xl mb-12">
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
            <input type="text" value={userForm.fullName} onChange={e => setUserForm({ ...userForm, fullName: e.target.value })} placeholder="NOM COMPLET" className="bg-gray-50 border-2 border-transparent focus:border-[#6186EA] p-5 rounded-2xl outline-none font-black text-sm uppercase" />
            <input type="text" value={userForm.username} onChange={e => setUserForm({ ...userForm, username: e.target.value })} placeholder="NOM D'UTILISATEUR" className="bg-gray-50 border-2 border-transparent focus:border-[#6186EA] p-5 rounded-2xl outline-none font-black text-sm uppercase" />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <input type="email" value={userForm.email} onChange={e => setUserForm({ ...userForm, email: e.target.value })} placeholder="EMAIL" className="bg-gray-50 border-2 border-transparent focus:border-[#6186EA] p-5 rounded-2xl outline-none font-black text-sm uppercase" />
            <input type="password" value={userForm.password} onChange={e => setUserForm({ ...userForm, password: e.target.value })} placeholder={editingUser ? "NOUVEAU MOT DE PASSE (OPTIONNEL)" : "MOT DE PASSE"} className="bg-gray-50 border-2 border-transparent focus:border-[#6186EA] p-5 rounded-2xl outline-none font-black text-sm uppercase" />
          </div>
          <div className="flex items-center gap-4">
            <label className="flex items-center gap-3 cursor-pointer">
              <input type="checkbox" checked={userForm.isAdmin} onChange={e => setUserForm({ ...userForm, isAdmin: e.target.checked })} className="w-5 h-5 accent-[#6186EA]" />
              <span className="text-xs font-black uppercase text-gray-500">Droits Administrateur</span>
            </label>
            <div className="flex-1"></div>
            {editingUser && (
              <button type="button" onClick={() => { setEditingUser(null); setUserForm({ fullName: '', username: '', email: '', isAdmin: false, password: '' }); }} className="bg-gray-100 text-black px-8 py-4 rounded-2xl font-black uppercase text-xs">Annuler</button>
            )}
            <button type="submit" className="bg-[#6186EA] text-white px-10 py-4 rounded-2xl font-black uppercase text-xs">
              {editingUser ? 'Enregistrer' : 'Créer le collaborateur'}
            </button>
          </div>
        </form>
      </div>

      <div className="grid gap-6">
        {allUsers.map(u => (
          <div key={u.id} className={`bg-white p-10 rounded-[40px] shadow-sm border-2 transition-all ${editingUser?.id === u.id ? 'border-[#6186EA]' : 'border-black/5'}`}>
            <div className="flex justify-between items-start mb-10">
              <div>
                <div className="flex items-center gap-3">
                  <h4 className="text-2xl font-black uppercase tracking-tighter">{u.full_name}</h4>
                  {u.is_admin && <span className="bg-black text-white text-[8px] px-2 py-0.5 rounded-full font-black uppercase tracking-widest">ADMIN</span>}
                </div>
                <p className="text-xs text-gray-400 font-black tracking-widest mt-1">@{u.username} • {u.email}</p>
              </div>
              <button
                onClick={() => {
                  setEditingUser(u);
                  setUserForm({ fullName: u.full_name, username: u.username, email: u.email, isAdmin: u.is_admin, password: '' });
                }}
                className="p-3 bg-gray-50 rounded-xl hover:bg-gray-100 transition-all text-gray-400 hover:text-black"
              >
                <Settings size={18} />
              </button>
            </div>

            <div>
              <h5 className="text-[10px] font-black uppercase tracking-widest mb-6 text-gray-400">Projets Associés</h5>
              <div className="grid grid-cols-3 gap-4">
                {projects.map(p => {
                  const isAssigned = (u.projects || []).some(up => up.id === p.id);
                  return (
                    <label key={p.id} className={`flex items-center gap-3 p-4 bg-gray-50 rounded-2xl cursor-pointer hover:bg-gray-100 transition-all border-2 ${isAssigned ? 'border-[#6186EA]' : 'border-transparent'}`}>
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
                      <Briefcase size={14} className={isAssigned ? "text-[#6186EA]" : "text-gray-300"} />
                      <span className="text-[10px] font-black uppercase text-gray-700">{p.name}</span>
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
      <div className="bg-white rounded-[40px] p-10 border-2 border-black shadow-2xl mb-12">
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
          <input type="text" value={projectNameInput} onChange={e => setProjectNameInput(e.target.value)} placeholder="NOM DU PROJET" className="w-full bg-gray-50 border-2 border-transparent focus:border-[#6186EA] p-5 rounded-3xl outline-none font-black text-sm uppercase" />
          <div className="flex gap-4">
            {['Mission', 'Formation', 'Interne'].map(cat => <button key={cat} type="button" onClick={() => setProjectCategoryInput(cat)} className={`flex-1 py-4 rounded-2xl font-black uppercase text-xs border-2 transition-all ${projectCategoryInput === cat ? 'bg-black text-white border-black' : 'border-gray-200 text-gray-400'}`}>{cat}</button>)}
          </div>
          <div className="flex gap-4">
            <button type="submit" className="flex-1 bg-[#6186EA] text-white p-6 rounded-3xl font-black uppercase text-sm">
              {editingProject ? 'Enregistrer les modifications' : 'Créer le projet'}
            </button>
            {editingProject && (
              <button
                type="button"
                onClick={() => { setEditingProject(null); setProjectNameInput(""); }}
                className="bg-gray-100 text-black p-6 rounded-3xl font-black uppercase text-sm"
              >
                Annuler
              </button>
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
            className={`bg-white p-6 rounded-3xl border-2 flex items-center justify-between shadow-sm cursor-pointer transition-all ${editingProject?.id === p.id ? 'border-[#6186EA]' : 'border-black/5 hover:border-black/20'}`}
          >
            <div className="flex items-center gap-4">
              <div className={`w-2 h-2 rounded-full ${p.category === 'Mission' ? 'bg-[#6186EA]' : p.category === 'Interne' ? 'bg-indigo-500' : 'bg-amber-400'}`}></div>
              <span className="font-black uppercase text-sm">{p.name}</span>
            </div>
            <div className="flex items-center gap-4">
              <span className="text-[10px] font-black text-gray-400 uppercase tracking-widest">{p.category}</span>
              <Settings size={14} className="text-gray-300" />
            </div>
          </div>
        ))}
      </div>
    </main>
  );

  const renderProfile = () => (
    <main className="max-w-xl mx-auto p-12">
      <div className="bg-white rounded-[50px] p-16 shadow-2xl border-2 border-black">
        <div className="text-center mb-10"><h2 className="text-4xl font-black uppercase tracking-tighter">{currentUser.full_name}</h2></div>
        <h3 className="text-xl font-black uppercase mb-8 flex items-center gap-3"><Lock size={20} /> Sécurité</h3>
        <form onSubmit={handlePassChange} className="space-y-6">
          <div className="space-y-2"><label className="text-[10px] font-black text-gray-400 tracking-widest uppercase ml-4">Ancien mot de passe</label><input type="password" value={passForm.old} onChange={e => setPassForm({ ...passForm, old: e.target.value })} className="w-full bg-gray-50 border-2 border-transparent focus:border-[#6186EA] p-5 rounded-2xl outline-none font-black text-sm" /></div>
          <div className="space-y-2"><label className="text-[10px] font-black text-gray-400 tracking-widest uppercase ml-4">Nouveau mot de passe</label><input type="password" value={passForm.new} onChange={e => setPassForm({ ...passForm, new: e.target.value })} className="w-full bg-gray-50 border-2 border-transparent focus:border-[#6186EA] p-5 rounded-2xl outline-none font-black text-sm" /></div>
          <div className="space-y-2"><label className="text-[10px] font-black text-gray-400 tracking-widest uppercase ml-4">Confirmer</label><input type="password" value={passForm.confirm} onChange={e => setPassForm({ ...passForm, confirm: e.target.value })} className="w-full bg-gray-50 border-2 border-transparent focus:border-[#6186EA] p-5 rounded-2xl outline-none font-black text-sm" /></div>
          <button type="submit" disabled={loading} className="w-full bg-[#6186EA] text-white p-6 rounded-2xl font-black uppercase text-sm flex items-center justify-center gap-3">
            {saveStatus === 'success' ? <CheckCircle2 size={20} /> : <Key size={18} />} {saveStatus === 'success' ? 'C\'est fait !' : 'Mettre à jour'}
          </button>
        </form>
      </div>
    </main>
  );

  return (
    <div className="min-h-screen bg-[#EDECEA] text-black font-['Work_Sans',sans-serif]">
      {renderHeader()}
      {!currentUser && renderLogin()}
      {currentUser && currentView === 'cra' && renderSpreadsheet()}
      {currentUser && currentView === 'projects' && renderProjectsView()}
      {currentUser && currentView === 'admin_cra' && renderAdminCRAView()}
      {currentUser && currentView === 'admin_global' && renderAdminGlobalView()}
      {currentUser && currentView === 'admin_users' && renderAdminUsersView()}
      {currentUser && currentView === 'profile' && renderProfile()}
    </div>
  )
}

export default App
