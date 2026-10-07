import React, {useEffect, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import Markdown from 'react-markdown';
import {ArrowUp, Plus, Search, FileText, MessageSquare, X, Upload, ChevronRight, Download, RefreshCw, Menu, AudioLines, LoaderCircle, ExternalLink, Check, Trash2} from './icons';
import './style.css';

type Meeting = {id:string;title:string;date:string|null;duration:number;cue_count:number;status:string;error:string|null;source_url:string|null};
type Cue = {idx:number;start:number;end:number;speaker:string|null;text:string};
type Source = {number:number;meeting_id:string;title:string;start:number;end:number;cue_start:number;cue_end:number;text?:string;deleted?:boolean};
type Usage = {cost?:number;estimated?:boolean};
type Message = {id:string;role:string;content:string;citations:Source[];usage:Usage};
type Chat = {id:string;title:string;meeting_id:string|null;messages?:Message[]};
type Config = {configured:boolean;chat_model:string;embedding_model:string;daily_budget:number;costs:{total:number;today:number;calls:number}};
type Result = Source & {id:number;text:string};
// Keep seconds formatting explicit for both short and long meetings.
const stamp = (seconds:number) => {const n=Math.floor(seconds);return (n>=3600?`${Math.floor(n/3600).toString().padStart(2,'0')}:`:'')+`${Math.floor(n/60)%60}`.padStart(2,'0')+':'+`${n%60}`.padStart(2,'0');};
const money=(n:number)=>`US$ ${n.toFixed(5)}`;
async function api<T>(path:string, options?:RequestInit):Promise<T> {
  const response=await fetch('/api'+path,options);
  if(!response.ok){let error='No se pudo completar la solicitud.';try{const data=await response.json();if(typeof data.detail==='string')error=data.detail;}catch{}throw new Error(error);}
  return response.json();
}
const json=(body:unknown)=>({method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});

function CredentialsForm({onConnected,onClose,onBusyChange}:{onConnected:()=>Promise<void>;onClose?:()=>void;onBusyChange?:(busy:boolean)=>void}){
  const [key,setKey]=useState(''),[visible,setVisible]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('');
  async function connect(e:React.FormEvent){e.preventDefault();if(busy)return;setBusy(true);onBusyChange?.(true);setError('');try{await api('/credentials',json({key:key.trim()}));setKey('');setVisible(false);await onConnected();}catch(e){setError((e as Error).message);}finally{setBusy(false);onBusyChange?.(false);}}
  return <form className="credentials-form" onSubmit={connect}>
    <p>Las consultas y la indexación se realizan con tu cuenta de OpenRouter.</p>
    <label htmlFor="openrouter-key">Tu clave de OpenRouter</label><div className="key-input"><input id="openrouter-key" type={visible?'text':'password'} value={key} autoComplete="off" autoCapitalize="none" spellCheck={false} maxLength={512} disabled={busy} placeholder="sk-or-v1-…" required onChange={e=>setKey(e.target.value)}/><button type="button" disabled={busy||!key} onClick={()=>setVisible(!visible)} aria-label={visible?'Ocultar clave':'Mostrar clave'}>{visible?'Ocultar':'Mostrar'}</button></div>
    <a className="text-link" href="https://openrouter.ai/settings/keys" target="_blank" rel="noreferrer">Obtener una clave en OpenRouter <ExternalLink size={14}/></a>
    <p className="key-note">La conexión dura hasta 8 horas. Al desconectarte o reiniciar la app tendrás que introducir la clave de nuevo. Tu navegador guarda únicamente un identificador de sesión.</p>
    {error&&<p className="banner error" role="alert">{error}</p>}
    <div className="dialog-actions">{onClose&&<button type="button" className="secondary" disabled={busy} onClick={onClose}>Cancelar</button>}<button className="primary" disabled={busy||!key.trim()}>{busy?<LoaderCircle size={16} className="spin"/>:<Check size={16}/>} {busy?'Verificando…':'Conectar mi clave'}</button></div>
  </form>;
}

function Dialog({title,children,onClose,className='',closeDisabled=false}:{title:string;children:React.ReactNode;onClose:()=>void;className?:string;closeDisabled?:boolean}){
  const ref=useRef<HTMLDialogElement>(null);
  useEffect(()=>{const previous=document.activeElement as HTMLElement|null;ref.current?.showModal();ref.current?.querySelector<HTMLButtonElement>('[data-initial-focus]')?.focus();return()=>{ref.current?.close();previous?.focus();};},[]);
  return <dialog ref={ref} className={className} onCancel={e=>{e.preventDefault();onClose();}} onClick={e=>{if(e.target===ref.current){const r=ref.current.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)onClose();}}} aria-label={title}>
    <div className="dialog-header"><h2>{title}</h2><button className="icon" disabled={closeDisabled} onClick={onClose} aria-label="Cerrar"><X size={20}/></button></div>{children}
  </dialog>;
}

function DeleteConfirmation({title,children,onClose,onDelete}:{title:string;children:React.ReactNode;onClose:()=>void;onDelete:()=>Promise<void>}){
  const [busy,setBusy]=useState(false),[error,setError]=useState('');
  async function submit(e:React.FormEvent){e.preventDefault();if(busy)return;setBusy(true);setError('');try{await onDelete();}catch(e){setError((e as Error).message);setBusy(false);}}
  return <Dialog title={title} className="delete-dialog" closeDisabled={busy} onClose={()=>{if(!busy)onClose();}}><form className="delete-form" onSubmit={submit}>
    {children}
    {error&&<p className="banner error" role="alert">{error}</p>}
    <div className="dialog-actions"><button type="button" data-initial-focus="true" className="secondary" disabled={busy} onClick={onClose}>Cancelar</button><button className="danger" disabled={busy}>{busy?<LoaderCircle size={16} className="spin"/>:<Trash2 size={16}/>} {busy?'Eliminando…':title}</button></div>
  </form></Dialog>;
}

function DeleteMeetingDialog({meeting,onClose,onDelete}:{meeting:Meeting;onClose:()=>void;onDelete:()=>Promise<void>}){
  return <DeleteConfirmation title="Eliminar reunión" onClose={onClose} onDelete={onDelete}>
    <p>Se eliminará <strong>{meeting.title}</strong> del archivo, junto con su transcripción, índice y chats dedicados a esta reunión.</p>
    <p className="muted small">Los chats de todas las reuniones conservarán sus mensajes, con las fuentes de esta reunión marcadas como eliminadas. Puedes volver a cargar el VTT cuando lo necesites.</p>
    <p className="small">Esta acción no se puede deshacer. El archivo original de tu equipo se conserva.</p>
  </DeleteConfirmation>;
}

function DeleteChatDialog({chat,onClose,onDelete}:{chat:Chat;onClose:()=>void;onDelete:()=>Promise<void>}){
  return <DeleteConfirmation title="Eliminar chat" onClose={onClose} onDelete={onDelete}>
    <p>Se eliminará <strong>{chat.title}</strong> junto con todos sus mensajes.</p>
    <p className="muted small">Las reuniones, sus transcripciones y los demás chats se conservan.</p>
    <p className="small">Esta acción no se puede deshacer.</p>
  </DeleteConfirmation>;
}

function UploadDialog({onClose,onDone}:{onClose:()=>void;onDone:(notice:string)=>void}){
  const [files,setFiles]=useState<File[]>([]),[title,setTitle]=useState(''),[date,setDate]=useState(''),[url,setUrl]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState(''),[progress,setProgress]=useState('');
  const pick=(list:File[])=>{setFiles(list);setTitle(list.length===1?list[0].name.replace(/\.vtt$/i,''):'');setError('');};
  async function submit(e:React.FormEvent){e.preventDefault();setBusy(true);setError('');let imported=0,duplicates=0;
    try{for(let i=0;i<files.length;i++){const file=files[i];setProgress(`Cargando ${i+1} de ${files.length} · ${file.name}`);const form=new FormData();form.append('file',file);form.append('title',files.length===1?title:file.name.replace(/\.vtt$/i,''));if(files.length===1){form.append('date',date);form.append('source_url',url);}const r=await api<{created:boolean}>('/meetings',{method:'POST',body:form});r.created?imported++:duplicates++;}
      onDone(`${imported?`${imported} archivo${imported===1?'':'s'} añadido${imported===1?'':'s'}. La indexación continúa en segundo plano.`:''}${duplicates?` ${duplicates} ya estaba${duplicates===1?'':'n'} en el archivo.`:''}`.trim());
    }catch(e){setError(`${(e as Error).message}${imported?` Se guardaron ${imported} archivos antes del error. Puedes reintentar; los duplicados se omiten.`:''}`);}finally{setBusy(false);}
  }
  return <Dialog title="Añadir transcripciones" onClose={()=>{if(!busy)onClose();}}><form onSubmit={submit} className="upload-form">
    <label className="dropzone" onDragOver={e=>e.preventDefault()} onDrop={e=>{e.preventDefault();if(!busy)pick(Array.from(e.dataTransfer.files));}}><Upload size={26}/><strong>Arrastra tus archivos VTT aquí</strong><span>o selecciónalos desde tu equipo</span><input type="file" accept=".vtt" multiple disabled={busy} onChange={e=>pick(Array.from(e.target.files||[]))}/><small>Hasta 10 MB por archivo · Puedes cargar varios a la vez</small></label>
    {files.length>0&&<div className="file-list">{files.map((f,i)=><div key={i}><FileText size={16}/><span>{f.name}</span><small>{Math.ceil(f.size/1024)} KB</small></div>)}</div>}
    {files.length===1&&<><label>Título<input value={title} maxLength={180} disabled={busy} onChange={e=>setTitle(e.target.value)}/></label><div className="form-grid"><label>Fecha de la reunión <span>Opcional</span><input type="date" value={date} disabled={busy} onChange={e=>setDate(e.target.value)}/></label><label>Enlace al origen <span>Opcional</span><input type="url" placeholder="https://…" value={url} disabled={busy} onChange={e=>setUrl(e.target.value)}/></label></div></>}
    <p className="muted small">Se conservarán los hablantes y las marcas de tiempo. El texto se envía a OpenRouter para crear el índice semántico y responder tus consultas.</p>
    {error&&<p role="alert" className="error">{error}</p>}{busy&&<p role="status" className="muted small">{progress}</p>}
    <div className="dialog-actions"><button type="button" className="secondary" disabled={busy} onClick={onClose}>Cancelar</button><button className="primary" disabled={!files.length||busy}>{busy?<LoaderCircle className="spin" size={16}/>:<Plus size={16}/>} {busy?'Cargando…':'Añadir al archivo'}</button></div>
  </form></Dialog>;
}

function Reader({meeting,range,onClose}:{meeting:Meeting&{cues:Cue[]};range:[number,number]|null;onClose:()=>void}){
  const [query,setQuery]=useState('');const selected=useRef<HTMLDivElement>(null);
  useEffect(()=>{if(range)requestAnimationFrame(()=>selected.current?.scrollIntoView({block:'center'}));},[range]);
  const visible=meeting.cues.filter(c=>!query||`${c.speaker||''} ${c.text}`.toLocaleLowerCase().includes(query.toLocaleLowerCase()));
  return <Dialog title={meeting.title} onClose={onClose} className="reader"><div className="reader-meta"><span>{meeting.date||'Fecha no indicada'} · {stamp(meeting.duration)} · {meeting.cue_count} intervenciones</span><a className="text-link" href={`/api/meetings/${meeting.id}/original`}><Download size={15}/> VTT original</a>{meeting.source_url&&<a className="text-link" href={meeting.source_url} target="_blank" rel="noreferrer"><ExternalLink size={15}/> Origen</a>}</div>
    <label className="reader-search"><Search size={17}/><input type="search" aria-label="Buscar en la transcripción" placeholder="Buscar texto o hablante en esta transcripción" value={query} onChange={e=>setQuery(e.target.value)}/></label>
    <div className="cues">{visible.length===0?<p className="muted">No hay coincidencias en esta transcripción.</p>:visible.map(c=>{const highlighted=range&&c.idx>=range[0]&&c.idx<=range[1];return <div key={c.idx} ref={range&&c.idx===range[0]?selected:undefined} className={`cue ${highlighted?'highlighted':''}`}><span className="timestamp">{stamp(c.start)}</span><div><strong>{c.speaker||'Sin hablante'}</strong><p>{c.text}</p></div></div>;})}</div>
  </Dialog>;
}

function citationsPlugin(){return (tree:any)=>{function walk(node:any){if(!node.children||node.type==='link'||node.type==='code')return;node.children=node.children.flatMap((child:any)=>{if(child.type!=='text'){walk(child);return [child];}const parts=[];let cursor=0;const rx=/\[(\d+)\]/g;let m;while((m=rx.exec(child.value))){if(m.index>cursor)parts.push({type:'text',value:child.value.slice(cursor,m.index)});parts.push({type:'link',url:'#citation-'+m[1],children:[{type:'text',value:m[1]}]});cursor=rx.lastIndex;}if(cursor<child.value.length)parts.push({type:'text',value:child.value.slice(cursor)});return parts;});}walk(tree);};}

function App(){
  const [credentialsOpen,setCredentialsOpen]=useState(false),[credentialBusy,setCredentialBusy]=useState(false),[disconnecting,setDisconnecting]=useState(false);
  const [removing,setRemoving]=useState<Meeting|null>(null);
  const [removingChat,setRemovingChat]=useState<Chat|null>(null);
  const [meetings,setMeetings]=useState<Meeting[]>([]),[chats,setChats]=useState<Chat[]>([]),[config,setConfig]=useState<Config|null>(null),[loading,setLoading]=useState(true),[scope,setScope]=useState(''),[active,setActive]=useState<Chat|null>(null),[messages,setMessages]=useState<Message[]>([]),[input,setInput]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState(''),[upload,setUpload]=useState(false),[mobileNav,setMobileNav]=useState(false),[view,setView]=useState<'chat'|'search'>('chat'),[searchInput,setSearchInput]=useState(''),[results,setResults]=useState<Result[]|null>(null),[reader,setReader]=useState<(Meeting&{cues:Cue[]})|null>(null),[range,setRange]=useState<[number,number]|null>(null);
  const end=useRef<HTMLDivElement>(null),composer=useRef<HTMLTextAreaElement>(null);
  const scoped=meetings.find(m=>m.id===scope);
  async function refresh(){const cfg=await api<Config>('/config');setConfig(cfg);if(!cfg.configured){setMeetings([]);setChats([]);setActive(null);setMessages([]);setReader(null);setUpload(false);setRemoving(null);setRemovingChat(null);setCredentialsOpen(false);return;}const [m,c]=await Promise.all([api<Meeting[]>('/meetings'),api<Chat[]>('/chats')]);setMeetings(m);setChats(c);}
  useEffect(()=>{refresh().catch(e=>setError(e.message)).finally(()=>setLoading(false));const timer=setInterval(()=>refresh().catch(()=>{}),5000);return()=>clearInterval(timer);},[]);
  useEffect(()=>{end.current?.scrollIntoView({behavior:'smooth',block:'end'});},[messages,busy]);
  function newChat(mid=scope){setScope(mid);setActive(null);setMessages([]);setInput('');setError('');setNotice('');setView('chat');setMobileNav(false);composer.current?.focus();}
  async function openChat(c:Chat){setBusy(true);setError('');try{const detail=await api<Chat>(`/chats/${c.id}`);setActive(detail);setScope(detail.meeting_id||'');setMessages(detail.messages||[]);setView('chat');setMobileNav(false);}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  async function openReader(mid:string,start?:number,last?:number){setError('');try{const m=await api<Meeting&{cues:Cue[]}>(`/meetings/${mid}`);setRange(start!==undefined?[start,last??start]:null);setReader(m);}catch(e){setError((e as Error).message);}}
  async function ask(question=input){if(!question.trim()||busy)return;setBusy(true);setError('');setNotice('');
    try{const chat=active||await api<Chat>('/chats',json({meeting_id:scope||null}));setActive(chat);const r=await api<{answer:string;citations:Source[];usage:Usage;warning:string|null}>(`/chats/${chat.id}/messages`,json({question}));const detail=await api<Chat>(`/chats/${chat.id}`);setMessages(detail.messages||[]);setInput('');if(r.warning)setNotice(r.warning);await refresh();}catch(e){setError((e as Error).message);setInput(question);}finally{setBusy(false);composer.current?.focus();}}
  async function search(e:React.FormEvent){e.preventDefault();if(!searchInput.trim()||busy)return;setBusy(true);setError('');setNotice('');try{const r=await api<{results:Result[];warning:string|null}>('/search',json({query:searchInput,meeting_id:scope||null}));setResults(r.results);if(r.warning)setNotice(r.warning);await refresh();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  async function reindex(mid:string){try{await api(`/meetings/${mid}/reindex`,json({}));setNotice('Indexación iniciada. Puedes seguir leyendo la transcripción.');await refresh();}catch(e){setError((e as Error).message);}}
  async function deleteMeeting(meeting:Meeting){
    const r=await api<{deleted:boolean;deleted_chat_ids:string[]}>(`/meetings/${meeting.id}`,{method:'DELETE'});
    setMeetings(items=>items.filter(m=>m.id!==meeting.id));setChats(items=>items.filter(c=>!r.deleted_chat_ids.includes(c.id)));setResults(items=>items?.filter(s=>s.meeting_id!==meeting.id)??null);
    if(reader?.id===meeting.id)setReader(null);
    if(active&&r.deleted_chat_ids.includes(active.id)){newChat('');}else{
      if(scope===meeting.id)setScope('');
      // Update unavailable sources immediately, even if refreshing later fails.
      setMessages(items=>items.map(m=>({...m,citations:m.citations.map(s=>s.meeting_id===meeting.id?{...s,text:undefined,deleted:true}:s)})));
    }
    setRemoving(null);setMobileNav(false);setNotice(`«${meeting.title}» eliminada del archivo.`);
    await refresh().catch(e=>setError((e as Error).message));
  }
  async function deleteChat(chat:Chat){
    await api(`/chats/${chat.id}`,{method:'DELETE'});
    setChats(items=>items.filter(c=>c.id!==chat.id));
    if(active?.id===chat.id)newChat();
    setRemovingChat(null);setMobileNav(false);setNotice('Chat eliminado.');
    await refresh().catch(e=>setError((e as Error).message));
  }
  async function disconnect(){setDisconnecting(true);setError('');try{await api('/credentials',{method:'DELETE'});setConfig(c=>c?{...c,configured:false}:null);setCredentialsOpen(false);setInput('');setSearchInput('');setResults(null);setScope('');await refresh();}catch(e){setError((e as Error).message);}finally{setDisconnecting(false);}}
  if(loading)return <div className="credentials-page"><div className="brand"><span className="brand-mark"><AudioLines size={22}/></span><div><strong>TranscribeAI</strong><span>Tu archivo de reuniones</span></div></div><p className="small muted" role="status">Cargando tu sesión…</p></div>;
  if(!config?.configured)return <div className="credentials-page"><section className="credentials-panel"><div className="brand"><span className="brand-mark"><AudioLines size={22}/></span><div><strong>TranscribeAI</strong><span>Tu archivo de reuniones</span></div></div><h1>Conecta tu OpenRouter.</h1><p className="credentials-intro">Encuentra lo que se dijo en tus reuniones usando tu propia clave.</p>{error&&<p className="banner error" role="alert">{error}</p>}<CredentialsForm onConnected={async()=>{setError('');await refresh();}}/></section></div>;
  const suggestion=['Resume los temas principales de la reunión','¿Qué acuerdos y próximos pasos quedaron definidos?','¿Qué se discutió sobre inteligencia artificial?'];
  return <div className="app"><aside className={`sidebar ${mobileNav?'open':''}`}>
    <div className="brand"><span className="brand-mark"><AudioLines size={22}/></span><div><strong>TranscribeAI</strong><span>Tu archivo de reuniones</span></div><button className="icon nav-close" aria-label="Cerrar menú" onClick={()=>setMobileNav(false)}><X size={20}/></button></div>
    <button className="primary add-button" onClick={()=>setUpload(true)}><Plus size={17}/> Añadir VTT</button>
    <nav className="mode-nav" aria-label="Herramientas"><button disabled={busy} className={view==='chat'?'selected':''} onClick={()=>{setView('chat');setMobileNav(false);}}><MessageSquare size={18}/> Chat con el archivo</button><button disabled={busy} className={view==='search'?'selected':''} onClick={()=>{setView('search');setMobileNav(false);}}><Search size={18}/> Buscar fragmentos</button></nav>
    <div className="archive-heading"><h2>REUNIONES</h2><span>{meetings.length}</span></div><div className="meeting-list">
      {loading?<p className="small muted">Cargando archivo…</p>:meetings.length===0?<p className="small muted">Tu archivo está vacío. Añade tu primera transcripción.</p>:meetings.map(m=><div className={`meeting-row ${scope===m.id?'active':''}`} key={m.id}><button className="meeting-main" disabled={busy} onClick={()=>newChat(m.id)}><FileText size={17}/><span><strong>{m.title}</strong><small>{m.date||'Sin fecha'} · {stamp(m.duration)}<span className={`status-dot ${m.status}`} title={m.status==='ready'?'Índice semántico listo':m.status==='error'?'Error de indexación':'Indexando'}/></small></span></button><button className="icon read-button" onClick={()=>openReader(m.id)} aria-label={`Leer ${m.title}`} title="Abrir transcripción"><ChevronRight size={18}/></button><button className="icon delete-button" disabled={busy} onClick={()=>setRemoving(m)} aria-label={`Eliminar ${m.title}`} title="Eliminar reunión"><Trash2 size={16}/></button></div>)}
    </div><div className="archive-heading"><h2>CHATS RECIENTES</h2><button className="icon" disabled={busy} onClick={()=>newChat()} aria-label="Nuevo chat"><Plus size={16}/></button></div><div className="chat-list">{chats.map(c=><div key={c.id} className={`chat-row ${active?.id===c.id?'active':''}`}><button disabled={busy} className="chat-main" onClick={()=>openChat(c)} title={c.title}><MessageSquare size={15}/><span>{c.title}</span></button><button className="icon delete-button" disabled={busy} onClick={()=>setRemovingChat(c)} aria-label={`Eliminar chat: ${c.title}`} title="Eliminar chat"><Trash2 size={15}/></button></div>)}{!chats.length&&<p className="small muted">Tus consultas aparecerán aquí.</p>}</div>
    <div className="sidebar-footer"><span className="connection"><span/>Tu OpenRouter conectado</span><div className="account-actions"><button className="text-link" disabled={busy||disconnecting} onClick={()=>setCredentialsOpen(true)}>Cambiar clave</button><button className="text-link" disabled={busy||disconnecting} onClick={disconnect}>{disconnecting?'Desconectando…':'Desconectar'}</button></div><div className="cost-line"><span>Tu uso hoy</span><strong>{money(config?.costs.today||0)}</strong></div><small className="muted">Presupuesto: US$ {config?.daily_budget??1}/día por clave</small></div>
  </aside>{mobileNav&&<button className="nav-backdrop" onClick={()=>setMobileNav(false)} aria-label="Cerrar menú"/>}
  <main><header className="topbar"><div className="page-title"><button className="icon nav-toggle" aria-label="Abrir menú" onClick={()=>setMobileNav(true)}><Menu size={22}/></button><span>{view==='chat'?'Conversaciones':'Buscar en el archivo'}</span></div><button className="secondary compact" disabled={busy} onClick={()=>newChat()}><Plus size={16}/> Nuevo chat</button></header>
    <div className="scopebar"><label htmlFor="scope">Consultar en</label><select id="scope" value={scope} disabled={busy} onChange={e=>{const currentView=view;newChat(e.target.value);setView(currentView);setResults(null);}} title="Cambiar el ámbito inicia un nuevo chat"><option value="">Todas las reuniones ({meetings.length})</option>{meetings.map(m=><option key={m.id} value={m.id}>{m.title}</option>)}</select>{scoped&&<button className="text-link scope-reader" onClick={()=>openReader(scoped.id)}><FileText size={15}/> Leer transcripción</button>}</div>
    {scoped?.status==='error'&&<div className="index-error"><span>{scoped.error} Puedes consultar por palabras.</span><button className="text-link" onClick={()=>reindex(scoped.id)}><RefreshCw size={15}/> Reintentar índice</button></div>}
    {(scoped?.status==='indexing'||scoped?.status==='pending')&&<div className="index-progress" role="status"><LoaderCircle size={15} className="spin"/> Preparando el índice semántico de esta reunión…</div>}
    {error&&<div className="banner error" role="alert"><span>{error}</span><button className="icon" aria-label="Cerrar error" onClick={()=>setError('')}><X size={17}/></button></div>}{notice&&<div className="banner notice" role="status"><span>{notice}</span><button className="icon" aria-label="Cerrar aviso" onClick={()=>setNotice('')}><X size={17}/></button></div>}
    {view==='chat'?<><section className="conversation" aria-label="Mensajes"><div className="conversation-inner">
      {!messages.length&&<div className="welcome"><span className="eyebrow">DEL DIÁLOGO A LA MEMORIA</span><h1>Lo hablamos.<br/>Ahora puedes encontrarlo.</h1><p>Pregunta a tus reuniones. Recupera lo que se dijo,<br className="desktop-break"/> con hablantes, contexto y el minuto exacto.</p>{meetings.length?<><div className="suggestions">{suggestion.map((s,i)=><button key={s} disabled={busy} onClick={()=>ask(s)}><span className="suggestion-number">0{i+1}</span><span>{s}</span><ChevronRight size={17}/></button>)}</div><div className="archive-summary"><Check size={15}/><span>{meetings.length} reunión{meetings.length===1?'':'es'} en tu archivo · {meetings.reduce((n,m)=>n+m.cue_count,0).toLocaleString('es')} intervenciones</span></div></>:<button className="primary" onClick={()=>setUpload(true)}><Upload size={17}/> Cargar mi primera transcripción</button>}</div>}
      {messages.map(m=><article key={m.id} className={`message ${m.role}`}><div className="message-label">{m.role==='user'?'TÚ':<><span className="mini-mark"><AudioLines size={14}/></span> TRANSCRIBEAI</>}</div><div className="markdown"><Markdown remarkPlugins={[citationsPlugin]} components={{a:({href,children})=>{const match=href?.match(/^#citation-(\d+)$/);const source=match?m.citations.find(s=>s.number===Number(match[1])):null;return source?.deleted?<span className="citation-inline citation-deleted" title={`Fuente ${source.number}: reunión eliminada`}>{children}</span>:source?<button className="citation-inline" onClick={()=>openReader(source.meeting_id,source.cue_start,source.cue_end)} aria-label={`Ver fuente ${source.number}, ${source.title}, ${stamp(source.start)}`}>{children}</button>:<a href={href} target="_blank" rel="noreferrer">{children}</a>;}}}>{m.content}</Markdown></div>
        {m.citations.length>0&&<div className="sources"><h3>FUENTES · {m.citations.length}</h3>{m.citations.map(s=><button key={s.number} disabled={s.deleted} className={s.deleted?'source-deleted':''} onClick={()=>openReader(s.meeting_id,s.cue_start,s.cue_end)}><span className="source-number">{s.number}</span><span className="source-title">{s.title}{s.deleted&&<span className="source-status"> · Reunión eliminada</span>}</span><span className="timestamp">{stamp(s.start)}–{stamp(s.end)}</span>{!s.deleted&&<ChevronRight size={15}/>}</button>)}</div>}{m.usage.cost!==undefined&&<p className="usage-note">{money(m.usage.cost)}{m.usage.estimated?' estimado':''} · respuesta</p>}</article>)}
      {busy&&<div className="thinking" role="status"><LoaderCircle size={17} className="spin"/> Consultando los fragmentos de tus reuniones…</div>}<div ref={end}/>
    </div></section><div className="composer-wrap"><form className="composer" onSubmit={e=>{e.preventDefault();ask();}}><label className="sr-only" htmlFor="question">Pregunta a tus reuniones</label><textarea id="question" ref={composer} value={input} maxLength={4000} rows={2} disabled={busy||!meetings.length} placeholder={meetings.length?'¿Qué necesitas recordar de tus reuniones?':'Carga un VTT para comenzar…'} onChange={e=>setInput(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.nativeEvent.isComposing){e.preventDefault();ask();}}}/><button className="send" aria-label="Enviar pregunta" disabled={busy||!input.trim()||!meetings.length}>{busy?<LoaderCircle className="spin" size={19}/>:<ArrowUp size={20}/>}</button></form><div className="composer-caption"><span>Las respuestas se basan en los fragmentos recuperados. Verifica las citas.</span><span className="model-name">{config?.chat_model.split('/').pop()}</span></div></div></>:<section className="search-view"><div className="search-intro"><span className="eyebrow">BUSCA EL MOMENTO</span><h1>Encuentra el fragmento.</h1><p className="muted">Busca un concepto en español o en el idioma de la reunión.</p></div><form className="search-form" onSubmit={search}><Search size={20}/><input type="search" aria-label="Concepto para buscar" value={searchInput} maxLength={4000} onChange={e=>setSearchInput(e.target.value)} placeholder="Por ejemplo: agentes, decisiones, próximos pasos…"/><button className="primary" disabled={busy||!searchInput.trim()}>{busy?<LoaderCircle size={16} className="spin"/>:'Buscar'}</button></form>{results&&<p className="result-count">{results.length} fragmento{results.length===1?'':'s'} encontrado{results.length===1?'':'s'}</p>}{results?.map(r=><button className="search-result" key={r.id} onClick={()=>openReader(r.meeting_id,r.cue_start,r.cue_end)}><div><FileText size={16}/><strong>{r.title}</strong><span className="timestamp">{stamp(r.start)}–{stamp(r.end)}</span><ChevronRight size={17}/></div><p>{r.text.slice(0,420)}{r.text.length>420?'…':''}</p></button>)}{results?.length===0&&<p className="empty-results">No encontramos fragmentos. Prueba con un término más concreto o consulta todas las reuniones.</p>}</section>}
  </main>{credentialsOpen&&<Dialog title="Cambiar tu clave de OpenRouter" closeDisabled={credentialBusy} onClose={()=>{if(!credentialBusy)setCredentialsOpen(false);}}><div className="credentials-dialog"><CredentialsForm onBusyChange={setCredentialBusy} onClose={()=>setCredentialsOpen(false)} onConnected={async()=>{setCredentialsOpen(false);setError('');await refresh();}}/></div></Dialog>} {removingChat&&<DeleteChatDialog chat={removingChat} onClose={()=>setRemovingChat(null)} onDelete={()=>deleteChat(removingChat)}/>} {removing&&<DeleteMeetingDialog meeting={removing} onClose={()=>setRemoving(null)} onDelete={()=>deleteMeeting(removing)}/>} {upload&&<UploadDialog onClose={()=>setUpload(false)} onDone={n=>{setUpload(false);setNotice(n);refresh().catch(e=>setError(e.message));}}/>}{reader&&<Reader meeting={reader} range={range} onClose={()=>setReader(null)}/>}</div>;
}
createRoot(document.getElementById('root')!).render(<App/>);
