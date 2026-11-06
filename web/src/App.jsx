import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Activity, Bell, Check, ChevronDown, CircleHelp, Clock3, Download, Hand, History, Home, Menu, Mic, Minus, Plus, Radio, RefreshCw, Settings, Siren, SlidersHorizontal, Upload, Volume2, Wifi, X } from 'lucide-react';

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000';
const WS = API.replace(/^http/, 'ws');
const SOUNDS = [
  { id: 'ALARM', name: 'Alarm', icon: Bell, color: 'cyan' },
  { id: 'VEHICLE_HORN', name: 'Vehicle Horn', icon: Volume2, color: 'violet' },
  { id: 'DOORBELL', name: 'Doorbell', icon: Bell, color: 'blue' },
  { id: 'KNOCKING', name: 'Knocking', icon: Hand, color: 'purple' },
  { id: 'SIREN', name: 'Siren', icon: Siren, color: 'violet' },
];
const PRESETS = ['Single Pulse', 'Double Pulse', 'Triple Pulse', 'Long Vibration', 'Repeated Pulses', 'Custom Pattern'];
const DEFAULTS = Object.fromEntries(SOUNDS.map((s) => [s.id, { preset: s.id === 'KNOCKING' ? 'Double Pulse' : 'Triple Pulse', intensity: 75, onMs: 240, offMs: 150, repeat: 2 }]));
const NAV = [{ id: 'overview', label: 'Overview', icon: Home }, { id: 'customize', label: 'Customize Vibrations', icon: SlidersHorizontal }, { id: 'history', label: 'Detection History', icon: History }, { id: 'device', label: 'Device Settings', icon: Settings }];
const emptyStatus = { detector: false, device: false, microphone: false, listening: false, microphone_rms: null, microphone_device: null, microphone_sample_rate: null, last_signal: null, device_ip: null };

function loadPatterns() { try { return { ...DEFAULTS, ...JSON.parse(localStorage.getItem('dhvani-patterns') || '{}') }; } catch { return { ...DEFAULTS }; } }
function timeLabel(value) { if (!value) return '—'; const d = new Date(value); return Number.isNaN(d.valueOf()) ? '—' : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }); }
function makePulses(p) { return Array.from({ length: Math.max(1, Math.min(p.repeat, 8)) }, (_, i) => ({ on_ms: p.onMs, off_ms: i === p.repeat - 1 ? 0 : p.offMs })); }

class AppErrorBoundary extends React.Component {
  constructor(props) { super(props); this.state = { failed: false }; }
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(error) { console.error('Dhvani Mitra interface error:', error); }
  render() {
    if (this.state.failed) return <div className="error-screen"><section className="panel recovery-panel"><Activity size={28}/><h2>We couldn’t display this page</h2><p>Your saved vibration settings are still in this browser. Return to Overview or reload the interface.</p><div><button className="button primary" onClick={() => { this.setState({ failed: false }); window.location.hash = '#overview'; }}>Back to Overview</button><button className="button outline" onClick={() => window.location.reload()}>Reload interface</button></div></section></div>;
    return this.props.children;
  }
}

function App() {
  const [page, setPage] = useState('overview');
  const [mobileNav, setMobileNav] = useState(false);
  const [patterns, setPatterns] = useState(loadPatterns);
  const [selected, setSelected] = useState('ALARM');
  const [saved, setSaved] = useState('');
  const [status, setStatus] = useState(emptyStatus);
  const [events, setEvents] = useState([]);
  const [current, setCurrent] = useState(null);
  const [wsState, setWsState] = useState('connecting');
  const [preview, setPreview] = useState(false);
  const [notice, setNotice] = useState('');
  const [addSoundOpen, setAddSoundOpen] = useState(false);
  const [customSounds, setCustomSounds] = useState(() => { try { const parsed = JSON.parse(localStorage.getItem('dhvani-custom-sounds') || '[]'); return parsed.filter((sound) => typeof sound.audioUrl === 'string' && sound.audioUrl.startsWith('data:') && sound.audioUrl.length < 12_000_000); } catch { return []; } });
  const [recording, setRecording] = useState(false);
  const [recordedBlob, setRecordedBlob] = useState(null);
  const [soundName, setSoundName] = useState('');
  const [soundFile, setSoundFile] = useState(null);
  const [soundError, setSoundError] = useState('');
  const wsRef = useRef(null);
  const mediaRecorderRef = useRef(null);
  const mediaStreamRef = useRef(null);
  const fileInputRef = useRef(null);
  const cfg = patterns[selected] || { preset: 'Single Pulse', intensity: 70, onMs: 250, offMs: 150, repeat: 1 };
  const selectedSound = SOUNDS.find((s) => s.id === selected);

  useEffect(() => {
    let stopped = false; let timer;
    const connect = () => {
      if (stopped) return;
      const socket = new WebSocket(`${WS}/ws/web`); wsRef.current = socket;
      socket.onopen = () => setWsState('connected');
      socket.onmessage = (event) => {
        let message; try { message = JSON.parse(event.data); } catch { return; }
        if (message.type === 'status') setStatus(message.status || emptyStatus);
        if (message.type === 'sound_detected') { setCurrent(message); setEvents((old) => [message, ...old].slice(0, 500)); }
        if (message.type === 'haptic_status') setEvents((old) => old.map((e) => e.event_id === message.event_id ? { ...e, delivery_status: message.status } : e));
        if (message.type === 'history') setEvents(message.events || []);
        if (message.type === 'notice') setNotice(message.message || '');
      };
      socket.onclose = () => { setWsState('disconnected'); if (!stopped) timer = setTimeout(connect, 1800); };
      socket.onerror = () => socket.close();
    };
    connect(); return () => { stopped = true; clearTimeout(timer); wsRef.current?.close(); };
  }, []);

  useEffect(() => {
    let stopped = false;
    const refreshStatus = async () => {
      try {
        const response = await fetch(`${API}/api/status`);
        if (!response.ok) return;
        const currentStatus = await response.json();
        if (!stopped) setStatus(currentStatus);
      } catch { /* The WebSocket connection reports backend availability. */ }
    };
    refreshStatus();
    const interval = setInterval(refreshStatus, 2000);
    return () => { stopped = true; clearInterval(interval); };
  }, []);

  useEffect(() => { localStorage.setItem('dhvani-patterns', JSON.stringify(patterns)); }, [patterns]);
  useEffect(() => { localStorage.setItem('dhvani-custom-sounds', JSON.stringify(customSounds)); }, [customSounds]);
  useEffect(() => () => { mediaStreamRef.current?.getTracks().forEach((track) => track.stop()); }, []);
  useEffect(() => { if (!preview) return; const t = setTimeout(() => setPreview(false), Math.max(1400, cfg.repeat * (cfg.onMs + cfg.offMs))); return () => clearTimeout(t); }, [preview, cfg]);
  const update = (key, value) => setPatterns((p) => ({ ...p, [selected]: { ...(p[selected] || cfg), [key]: value } }));
  const send = (data) => { if (wsRef.current?.readyState === WebSocket.OPEN) wsRef.current.send(JSON.stringify(data)); else setNotice('Backend is disconnected. Your saved settings remain available in this browser.'); };
  const savePattern = async () => { localStorage.setItem('dhvani-patterns', JSON.stringify(patterns)); setSaved(selected); setTimeout(() => setSaved(''), 1800); const payload = { type: 'update_pattern', category: selected, intensity: cfg.intensity, repeat: cfg.repeat, pulses: makePulses(cfg), preset: cfg.preset }; send(payload); try { await fetch(`${API}/api/patterns/${selected}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }); } catch { /* Browser storage remains the local fallback. */ } };
  const testWristband = () => { if (!status.device) return setNotice('Wristband is disconnected. Connect the ESP32-C6 before testing.'); send({ type: 'test_haptic', category: selected, intensity: cfg.intensity, repeat: cfg.repeat, pulses: makePulses(cfg) }); };
  const resetPattern = () => setPatterns((p) => ({ ...p, [selected]: { ...(DEFAULTS[selected] || { preset: 'Single Pulse', intensity: 70, onMs: 250, offMs: 150, repeat: 1 }) } }));
  const openAddSound = () => { setSoundError(''); setSoundFile(null); setRecordedBlob(null); setSoundName(''); setAddSoundOpen(true); };
  const closeAddSound = () => { if (mediaRecorderRef.current?.state === 'recording') mediaRecorderRef.current.stop(); mediaStreamRef.current?.getTracks().forEach((track) => track.stop()); mediaStreamRef.current = null; setRecording(false); setAddSoundOpen(false); };
  const startRecording = async () => {
    setSoundError('');
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) { setSoundError('Audio recording is not supported in this browser. Try uploading an audio file instead.'); return; }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      mediaStreamRef.current = stream;
      const recorder = new MediaRecorder(stream); const chunks = [];
      recorder.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data); };
      recorder.onstop = () => { setRecordedBlob(new Blob(chunks, { type: recorder.mimeType || 'audio/webm' })); stream.getTracks().forEach((track) => track.stop()); mediaStreamRef.current = null; setRecording(false); };
      mediaRecorderRef.current = recorder; recorder.start(); setRecording(true);
    } catch (error) { setSoundError(error?.name === 'NotAllowedError' ? 'Microphone permission was denied. You can still upload a recording.' : 'Could not start microphone recording. You can still upload a recording.'); }
  };
  const stopRecording = () => { if (mediaRecorderRef.current?.state === 'recording') mediaRecorderRef.current.stop(); };
  const saveCustomSound = () => {
    const name = soundName.trim(); const audio = soundFile || recordedBlob;
    if (!name) { setSoundError('Enter a name for this sound profile.'); return; }
    if (!audio) { setSoundError('Upload an audio file or record a sound before saving.'); return; }
    if (audio.size > 8 * 1024 * 1024) { setSoundError('Keep recordings under 8 MB so they can be saved in this browser.'); return; }
    const reader = new FileReader();
    reader.onload = () => {
      const item = { id: `CUSTOM_${Date.now()}`, name, audioUrl: reader.result, mimeType: audio.type || 'audio/webm', addedAt: new Date().toISOString() };
      setCustomSounds((items) => [...items, item]);
      setPatterns((items) => ({ ...items, [item.id]: { preset: 'Single Pulse', intensity: 70, onMs: 250, offMs: 150, repeat: 1 } }));
      setAddSoundOpen(false); setSelected(item.id); setSoundName(''); setSoundFile(null); setRecordedBlob(null);
      setNotice(`“${name}” was added as a local sound profile. Connect it to a trained detector class before it can be detected automatically.`);
    };
    reader.onerror = () => setSoundError('Could not read that audio file. Please try another recording.');
    reader.readAsDataURL(audio);
  };
  const playCustomSound = (sound) => { const audio = new Audio(sound.audioUrl); audio.play().catch(() => setNotice('This recording could not be played by the browser.')); };
  const clearHistory = async () => { try { await fetch(`${API}/api/history`, { method: 'DELETE' }); setEvents([]); setCurrent(null); } catch { setNotice('Could not reach the backend to clear history.'); } };
  const exportHistory = () => { const blob = new Blob([JSON.stringify(events, null, 2)], { type: 'application/json' }); const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = 'dhvani-detection-history.json'; a.click(); URL.revokeObjectURL(url); };
  const counts = useMemo(() => Object.fromEntries(SOUNDS.map((s) => [s.id, events.filter((e) => e.category === s.id).length])), [events]);
  const title = NAV.find((n) => n.id === page)?.label.toUpperCase() || 'OVERVIEW';
  const navigate = (next) => {
    setPage(NAV.some((n) => n.id === next) ? next : 'overview');
    window.history.replaceState(null, '', `#${NAV.some((n) => n.id === next) ? next : 'overview'}`);
    setMobileNav(false);
    setNotice('');
  };

  useEffect(() => {
    const fromHash = window.location.hash.slice(1);
    if (NAV.some((n) => n.id === fromHash)) setPage(fromHash);
    const onHashChange = () => {
      const next = window.location.hash.slice(1);
      setPage(NAV.some((n) => n.id === next) ? next : 'overview');
    };
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  return <div className="app-shell">
    <aside className={`sidebar ${mobileNav ? 'sidebar-open' : ''}`}>
      <div className="brand"><span className="brand-mark"><Activity size={20} /></span><span>DHVANI MITRA</span><button className="mobile-close icon-button" onClick={() => setMobileNav(false)} aria-label="Close navigation"><X size={19}/></button></div>
      <nav>{NAV.map(({ id, label, icon: Icon }) => <button key={id} className={`nav-item ${page === id ? 'active' : ''}`} onClick={() => navigate(id)}><Icon size={17}/><span>{label}</span>{page === id && <span className="nav-check"><Check size={12}/></span>}</button>)}</nav>
      <div className="sidebar-foot"><span className={`tiny-dot ${wsState === 'connected' ? 'green' : 'amber'}`}/><span>Bridge {wsState === 'connected' ? 'online' : wsState === 'connecting' ? 'connecting' : 'offline'}</span></div>
    </aside>
    {mobileNav && <button className="backdrop" onClick={() => setMobileNav(false)} aria-label="Close navigation"/>}
    <main className="main-area">
      <header className="topbar"><button className="mobile-menu icon-button" onClick={() => setMobileNav(true)} aria-label="Open navigation"><Menu size={20}/></button><h1>{title}</h1><div className="top-status"><StatusBadge label="Python Detector" online={status.detector}/><StatusBadge label="Wristband" online={status.device} suffix="ESP32-C6"/></div></header>
      {notice && <button className="notice" onClick={() => setNotice('')}><CircleHelp size={15}/>{notice}<X size={14}/></button>}
      <div className="page-content">
        {page === 'overview' && <Overview status={status} wsState={wsState} events={events} current={current} patterns={patterns} onEdit={(id) => { setSelected(id); navigate('customize'); }} />}
        {page === 'customize' && <section className="custom-page">
          <SectionTitle n="1" title="Select Sound"/><div className="sound-selectors">{SOUNDS.map(({ id, name, icon: Icon, color }) => <button key={id} onClick={() => setSelected(id)} className={`sound-selector ${selected === id ? 'selected' : ''}`}><Icon className={color} size={19}/><span>{name}</span>{selected === id && <Check className="selector-check" size={15}/>}</button>)}{customSounds.map((sound) => <button key={sound.id} onClick={() => setSelected(sound.id)} className={`sound-selector ${selected === sound.id ? 'selected' : ''}`}><Activity className="cyan" size={19}/><span>{sound.name}</span>{selected === sound.id && <Check className="selector-check" size={15}/>}</button>)}<button className="sound-selector add-sound-button" onClick={openAddSound}><Plus size={19}/><span>Add Sound</span></button></div>
          {customSounds.some((sound) => sound.id === selected) && <div className="custom-sound-note panel"><span>This is a saved local audio profile. Automatic recognition requires a matching class in the Python detector.</span><button className="button outline" onClick={() => playCustomSound(customSounds.find((sound) => sound.id === selected))}>Play Recording</button></div>}
          <SectionTitle n="2" title="Configure Vibration"/><div className="config-grid">
            <div className="panel settings-panel"><h3>Settings &amp; Pattern</h3><label className="field-label">Pattern Preset</label><div className="preset-grid">{PRESETS.map((p) => <button key={p} onClick={() => update('preset', p)} className={`preset ${cfg.preset === p ? 'chosen' : ''}`}>{p}</button>)}</div>
              <RangeControl label="Intensity" value={cfg.intensity} min={0} max={100} unit="%" onChange={(v) => update('intensity', v)}/>
              <RangeControl label="Pulse Duration" value={cfg.onMs} min={50} max={1000} step={10} unit="ms" onChange={(v) => update('onMs', v)}/>
              <RangeControl label="Pause Duration" value={cfg.offMs} min={0} max={1000} step={10} unit="ms" onChange={(v) => update('offMs', v)}/>
              <div className="repeat-row"><span>Repeat Count</span><div className="stepper"><button onClick={() => update('repeat', Math.max(1, cfg.repeat - 1))} aria-label="Decrease repeat count"><Minus size={14}/></button><strong>{cfg.repeat}</strong><button onClick={() => update('repeat', Math.min(8, cfg.repeat + 1))} aria-label="Increase repeat count"><Plus size={14}/></button></div></div>
            </div>
            <div className="panel preview-panel"><h3>Pattern Preview &amp; Test</h3><div className="field-label">Pattern Timeline</div><Timeline cfg={cfg} active={preview}/><div className="preview-caption">Visual preview only — no motor vibration</div><div className="preview-actions"><button className="button primary" onClick={() => setPreview(true)}><Activity size={16}/>Preview Pattern Animation</button><button className="button outline" onClick={testWristband} disabled={!status.device}><Radio size={16}/>Test on Wristband <small>{status.device ? 'Connected' : 'ESP32-C6 connection required'}</small></button></div></div>
          </div><div className="save-actions"><button className="button primary save-button" onClick={savePattern}>{saved === selected ? <Check size={16}/> : null}{saved === selected ? 'Saved' : 'Save Changes'}</button><button className="button secondary" onClick={resetPattern}>Reset to Default</button></div>
        </section>}
        {!NAV.some((n) => n.id === page) && <section className="panel recovery-panel"><h2>Page could not be displayed</h2><p>The interface hit an unexpected state. Return to Overview and try again.</p><button className="button primary" onClick={() => navigate('overview')}>Back to Overview</button></section>}
        {page === 'history' && <HistoryPage events={events} counts={counts} onClear={clearHistory} onExport={exportHistory}/>}
        {page === 'device' && <DevicePage status={status} wsState={wsState} onTest={testWristband} onSync={() => send({ type: 'sync_config', patterns })} />}
      </div>
    </main>
    {addSoundOpen && <div className="dialog-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) closeAddSound(); }}><section className="add-sound-dialog panel" role="dialog" aria-modal="true" aria-labelledby="add-sound-title"><div className="dialog-header"><div><span className="dialog-kicker">CUSTOM SOUND PROFILE</span><h2 id="add-sound-title">Add a sound</h2></div><button className="icon-button dialog-close" aria-label="Close dialog" onClick={closeAddSound}><X size={19}/></button></div><p className="dialog-copy">Upload an existing recording or record a sound using your microphone. The audio stays in this browser.</p><label className="field-label" htmlFor="custom-sound-name">Sound name</label><input className="sound-name-input" id="custom-sound-name" placeholder="e.g. My door chime" value={soundName} onChange={(event) => setSoundName(event.target.value)} maxLength={40}/><div className="sound-source-actions"><input ref={fileInputRef} type="file" accept="audio/*" className="visually-hidden" onChange={(event) => { const file = event.target.files?.[0]; if (file) { setSoundFile(file); setRecordedBlob(null); setSoundError(''); } }}/><button className="button outline source-button" onClick={() => fileInputRef.current?.click()}><Upload size={17}/><span>Upload recording<small>Choose an audio file</small></span></button>{recording ? <button className="button record-button recording" onClick={stopRecording}><span className="record-dot"/>Stop recording<small>Recording from microphone…</small></button> : <button className="button outline source-button" onClick={startRecording}><Mic size={17}/><span>Record a sound<small>Use your microphone</small></span></button>}</div><div className="recording-status">{soundFile ? <span><Check size={14}/>Ready: {soundFile.name}</span> : recordedBlob ? <span><Check size={14}/>Recording ready ({Math.max(1, Math.round(recordedBlob.size / 1024))} KB)</span> : recording ? <span><i className="record-dot"/>Recording… select “Stop recording” when finished</span> : <span>Audio formats supported by your browser · Max 8 MB</span>}</div>{soundError && <p className="sound-error" role="alert">{soundError}</p>}<div className="dialog-footer"><button className="button secondary" onClick={closeAddSound}>Cancel</button><button className="button primary" onClick={saveCustomSound}><Plus size={16}/>Save Sound Profile</button></div></section></div>}
  </div>;
}

function StatusBadge({ label, online, suffix }) { return <div className={`status-badge ${online ? 'online' : ''}`}><span>{label}:</span><strong>{online ? `CONNECTED${suffix ? ` (${suffix})` : ''}` : 'DISCONNECTED'}</strong></div>; }
function SectionTitle({ n, title }) { return <h2 className="section-title"><span>{n}.</span> {title}</h2>; }
function RangeControl({ label, value, min, max, step = 1, unit, onChange }) { return <label className="range-row"><span>{label}</span><input type="range" min={min} max={max} step={step} value={value} style={{ '--range-progress': `${((value - min) / (max - min)) * 100}%` }} onChange={(e) => onChange(Number(e.target.value))}/><strong>{value}{unit}</strong></label>; }
function Timeline({ cfg, active }) { const count = Math.max(1, Math.min(cfg.repeat, 5)); return <div className={`timeline ${active ? 'timeline-active' : ''}`}><div className="timeline-track">{Array.from({ length: count }, (_, i) => <React.Fragment key={i}><div className={`pulse-block ${active ? 'pulse-playing' : ''}`} style={{ animationDelay: `${i * (cfg.onMs + cfg.offMs)}ms` }}><Activity size={25}/></div>{i < count - 1 && <div className="pause-block">PAUSE<br/><small>({cfg.offMs}ms)</small></div>}</React.Fragment>)}</div><div className="timeline-labels">{Array.from({ length: count }, (_, i) => <span key={i}>VIBRATE<br/>({cfg.onMs}ms)</span>)}</div></div>; }
function Overview({ status, wsState, events, current, patterns, onEdit }) {
  const detectorOn = status.detector;
  return <div className="overview-page"><div className="overview-top"><section><SectionTitle n="1" title="System Status"/><div className="panel listening-card"><div className={`listening-banner ${status.listening && detectorOn ? 'is-listening' : ''}`}><strong>{status.listening && detectorOn ? 'LISTENING' : 'STOPPED'}</strong><div className="waveform">{Array.from({ length: 38 }, (_, i) => <i key={i} style={{ height: `${7 + ((i * 23 + 9) % 25)}px` }}/>)}</div></div><div className="status-line"><span title={status.microphone_device || 'Laptop microphone'}><i className={status.microphone ? 'good' : ''}/>Microphone: <b>{status.microphone ? 'ACTIVE' : 'NOT REPORTED'}</b>{status.microphone_rms != null && <small className='mic-level'>RMS {status.microphone_rms.toFixed(4)}</small>}</span><span><i className={wsState === 'connected' ? 'good' : ''}/>WebSocket: <b>{wsState === 'connected' ? 'CONNECTED' : wsState.toUpperCase()}</b></span></div></div></section>
    <section><SectionTitle n="2" title="Current Sound Detection"/><div className="panel current-card">{current ? <><div className="detected-chip"><Activity size={16}/> DETECTED</div><strong className="current-name">{SOUNDS.find((s) => s.id === current.category)?.name || current.category}</strong><div className="current-meta"><span>{Math.round((current.confidence || 0) * 100)}% confidence</span><span>{timeLabel(current.timestamp)}</span></div></> : <><p>LISTENING FOR IMPORTANT<br/>ENVIRONMENTAL SOUNDS...</p><div className="quiet-wave">{Array.from({ length: 24 }, (_, i) => <i key={i} style={{ height: `${4 + (i * 13 % 17)}px` }}/>)}</div></>}</div></section></div>
    <section className="category-section"><SectionTitle n="3" title="Sound Categories"/><div className="category-grid">{SOUNDS.map((s) => { const Icon = s.icon; const last = events.find((e) => e.category === s.id); return <article className="panel category-card" key={s.id}><div className="category-title"><Icon className={s.color} size={21}/><strong>{s.name}</strong></div><p>Last Detected: <span>{last ? timeLabel(last.timestamp) : 'None'}</span></p><p>Vibration Pattern:<br/><span>{patterns[s.id]?.preset || 'Default'}</span></p><button className="button outline edit-pattern" onClick={() => onEdit(s.id)}>Edit Pattern</button></article>; })}</div></section>
    <section className="recent-section"><div className="section-heading-row"><SectionTitle n="4" title="Recent Detection History"/><span className="live-label"><i/>LIVE DATA</span></div><EventTable events={events.slice(0, 6)} compact/></section></div>;
}
function EventTable({ events, compact = false }) { return <div className="panel table-wrap"><table><thead><tr><th>Sound</th><th>Timestamp</th><th>Confidence</th>{!compact && <th>Haptic Pattern Used</th>}<th>Status / Delivery</th></tr></thead><tbody>{events.length ? events.map((e, i) => <tr key={e.event_id || `${e.timestamp}-${i}`}><td>{SOUNDS.find((s) => s.id === e.category)?.name || e.category}</td><td>{timeLabel(e.timestamp)}</td><td>{Math.round((e.confidence || 0) * 100)}%</td>{!compact && <td>{e.pattern_name || '—'}</td>}<td><DeliveryStatus status={e.delivery_status}/></td></tr>) : <tr><td colSpan={compact ? 4 : 5} className="empty-row">No detections received yet. Events from the Python detector will appear here.</td></tr>}</tbody></table></div>; }
function DeliveryStatus({ status }) { const label = status === 'acknowledged' ? 'ESP32 acknowledged' : status === 'sent' ? 'Command sent' : status === 'unavailable' ? 'Wristband offline' : status === 'error' ? 'Delivery error' : 'Awaiting device'; return <span className={`delivery ${status || 'pending'}`}><i/>{label}</span>; }
function HistoryPage({ events, counts, onClear, onExport }) { const [filter, setFilter] = useState('ALL'); const filtered = filter === 'ALL' ? events : events.filter((e) => e.category === filter); return <section className="history-page"><SectionTitle n="1" title="History Summary & Actions"/><div className="panel summary-panel"><div className="summary-top"><span>Total Detections: <strong>{events.length}</strong></span><div className="history-actions"><button className="button danger-outline" onClick={onClear} disabled={!events.length}>Clear History</button><button className="button outline" onClick={onExport} disabled={!events.length}><Download size={15}/>Export History</button></div></div><div className="count-pills">{SOUNDS.map((s) => <span key={s.id}>{s.name}: <b>{counts[s.id] || 0}</b></span>)}</div></div><div className="history-table-heading"><SectionTitle n="2" title="Sound Detections Log"/><label>Filter by Sound: <select value={filter} onChange={(e) => setFilter(e.target.value)}><option value="ALL">All</option>{SOUNDS.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select></label></div><div className="panel table-wrap"><table><thead><tr><th>Sound Type</th><th>Date &amp; Time</th><th>Confidence</th><th>Haptic Pattern Used</th><th>Status / Delivery</th></tr></thead><tbody>{filtered.length ? filtered.map((e, i) => <tr key={e.event_id || `${e.timestamp}-${i}`}><td>{SOUNDS.find((s) => s.id === e.category)?.name || e.category}</td><td>{new Date(e.timestamp).toLocaleString()}</td><td>{Math.round((e.confidence || 0) * 100)}%</td><td>{e.pattern_name || '—'}</td><td><DeliveryStatus status={e.delivery_status}/></td></tr>) : <tr><td colSpan="5" className="empty-row">{events.length ? 'No detections match this filter.' : 'No real detection events have been received yet.'}</td></tr>}</tbody></table></div></section>; }
function DevicePage({ status, wsState, onTest, onSync }) { const [testPattern, setTestPattern] = useState('Single Pulse'); return <div className="device-grid"><section><SectionTitle n="1" title="Wristband Status (ESP32-C6)"/><div className="panel device-status-panel"><div className={`connection-state ${status.device ? 'connected' : ''}`}>{status.device ? 'CONNECTED' : 'DISCONNECTED'}<Wifi size={24}/></div><p><i className={status.device ? 'good' : ''}/>WebSocket Server: <span>{status.device ? 'Connected (Active)' : 'Waiting for device'}</span></p><p><i className={status.device_ip ? 'good' : ''}/>Device IP: <span>{status.device_ip || 'Not reported'}</span></p><p><i className={status.last_signal ? 'good' : ''}/>Last Signal / Comm Time: <span>{status.last_signal ? timeLabel(status.last_signal) : 'Not reported'}</span></p><p className="muted-line"><i/>Battery: not reported by hardware</p></div><SectionTitle n="3" title="Sync Configuration"/><div className="panel sync-panel"><p>Send your saved sound patterns to the wristband when it connects.</p><p>Connection state: <b className={status.device ? 'green-text' : 'muted-text'}>{status.device ? 'Connected' : 'Disconnected'}</b></p><button className="button primary" onClick={onSync} disabled={!status.device}><RefreshCw size={16}/>Sync Configuration with Band</button></div></section><section><SectionTitle n="2" title="Active Control Tests"/><div className="panel test-panel"><h3>Test vibration on the wristband</h3><label className="field-label" htmlFor="test-pattern">Choose Test Vibration</label><div className="select-wrap"><select id="test-pattern" value={testPattern} onChange={(e) => setTestPattern(e.target.value)}>{PRESETS.slice(0, 5).map((p) => <option key={p}>{p}</option>)}</select><ChevronDown size={16}/></div><button className="button outline wide" onClick={onTest} disabled={!status.device}>Test Pattern Vibration</button>{!status.device && <small className="required-hint">ESP32-C6 connection required</small>}</div><SectionTitle n="4" title="Connection Status"/><div className="panel connection-info"><p><span className={`tiny-dot ${status.detector ? 'green' : ''}`}/>Python Detector: <b>{status.detector ? 'Connected' : 'Disconnected'}</b></p><p><span className={`tiny-dot ${wsState === 'connected' ? 'green' : ''}`}/>WebSocket: <b>{wsState === 'connected' ? 'Connected' : 'Disconnected'}</b></p><p><span className={`tiny-dot ${status.device ? 'green' : ''}`}/>Wristband: <b>{status.device ? 'Connected' : 'Disconnected'}</b></p></div></section></div>; }

export { AppErrorBoundary };
export default App;
