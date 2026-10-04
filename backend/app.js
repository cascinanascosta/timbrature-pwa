const A=document.getElementById('app');
let session=localStorage.getItem('session');
let name=localStorage.getItem('name')||'';
async function api(url,opt={}){
  opt.headers={...(opt.headers||{}),'Content-Type':'application/json'};
  if(session) url+=(url.includes('?')?'&':'?')+'session='+encodeURIComponent(session);
  const r=await fetch(url,opt); let d={}; try{d=await r.json()}catch{}
  if(!r.ok){if(r.status===401){logout();}throw new Error(d.detail||'Errore');}
  return d;
}
function login(){
 A.innerHTML=`<div class="box"><h1>Timbrature</h1><p>Accedi per timbrare.</p>
 <input id="u" placeholder="Nome utente" value="${localStorage.getItem('user')||''}" autocomplete="username">
 <input id="p" type="password" placeholder="Password" autocomplete="current-password">
 <label><input id="rem" type="checkbox"> Ricorda nome utente</label>
 <button onclick="doLogin()">ACCEDI</button><small>Demo: demo / demo123</small></div>`;
}
async function doLogin(){try{
 const r=await api('/api/login',{method:'POST',body:JSON.stringify({username:u.value.trim(),password:p.value})});
 session=r.session;name=r.name;localStorage.setItem('session',session);localStorage.setItem('name',name);
 if(rem.checked)localStorage.setItem('user',u.value.trim());else localStorage.removeItem('user');
 if(r.role==='admin')admin();else home();
}catch(e){alert(e.message)}}
async function home(){
 A.innerHTML=`<div class="box"><h2>Ciao ${name}</h2><p>Quando sei davanti al QR della sede, premi il pulsante.</p>
 <button onclick="scan()">📷 SCANSIONA QR</button><button onclick="history()">LE MIE TIMBRATURE</button><button onclick="logout()">ESCI</button></div>`;
}
async function scan(){
 A.innerHTML=`<div class="box"><h2>Scansiona QR</h2><p id="scanmsg">Consenti l'accesso alla fotocamera.</p><div id="reader" style="width:100%"></div><button onclick="stopScan();home()">ANNULLA</button></div>`;
 if(!window.isSecureContext){
   document.getElementById('scanmsg').textContent='La fotocamera richiede HTTPS. Apri la PWA tramite il link Render HTTPS.'; return;
 }
 try{
   if(!window.Html5Qrcode){
     const s=document.createElement('script'); s.src='https://unpkg.com/html5-qrcode@2.3.8/html5-qrcode.min.js';
     document.head.appendChild(s); await new Promise((res,rej)=>{s.onload=res;s.onerror=rej});
   }
   window.scanner=new Html5Qrcode('reader');
   const cameras=await Html5Qrcode.getCameras();
   if(!cameras||!cameras.length) throw new Error('Nessuna fotocamera disponibile');
   const back=cameras.find(c=>/back|rear|environment|posteriore/i.test(c.label));
   const cameraId=(back||cameras[0]).id;
   await window.scanner.start(cameraId,{fps:10,qrbox:{width:250,height:250}},async(decodedText)=>{
     try{
       await window.scanner.stop(); window.scanner.clear(); window.scanner=null;
       const r=await api('/api/punch',{method:'POST',body:JSON.stringify({token:decodedText})});
       A.innerHTML=`<div class="box"><div class="ok"><h2>✓ ${r.kind} REGISTRATA</h2><p>${r.name}<br>${r.timestamp}</p></div><button onclick="home()">TORNA ALLA HOME</button></div>`;
     }catch(e){alert(e.message);}
   });
 }catch(e){
   document.getElementById('scanmsg').textContent='Fotocamera non disponibile: '+e.message;
 }
}
async function stopScan(){try{if(window.scanner){await window.scanner.stop();window.scanner.clear();window.scanner=null;}}catch(e){}}
async function history(){try{
 const r=await api('/api/my-punches');
 if(!r.visible){A.innerHTML=`<div class="box"><h2>Le mie timbrature</h2><p>La consultazione del mese precedente è disponibile solo fino al giorno 6 del mese corrente.</p><button onclick="home()">INDIETRO</button></div>`;return;}
 A.innerHTML=`<div class="box"><h2>Timbrature ${r.month}</h2>${r.punches.map(x=>`<div class="row"><b>${x.kind}</b><span>${x.ts}</span></div>`).join('')||'<p>Nessuna timbratura.</p>'}<button onclick="home()">INDIETRO</button></div>`;
}catch(e){alert(e.message)}}
async function admin(){try{
 const [ps,us]=await Promise.all([api('/api/admin/punches'),api('/api/admin/users')]);
 A.innerHTML=`<div class="box"><h1>Admin</h1><p>Timbrature recenti: ${ps.length}</p><div>${ps.slice(0,50).map(x=>`<div class="row"><span><b>${x.name}</b><br>${new Date(x.ts).toLocaleString('it-IT')}</span><b>${x.kind}</b></div>`).join('')}</div><h3>Dipendenti</h3>${us.map(x=>`<div class="row"><span>${x.name}<br><small>${x.username}</small></span><span>${x.active?'🟢':'⚪'}</span></div>`).join('')}<button onclick="logout()">ESCI</button></div>`;
}catch(e){alert(e.message)}}
function logout(){stopScan();localStorage.removeItem('session');session=null;name='';login()}
if('serviceWorker' in navigator) navigator.serviceWorker.register('/static/sw.js').catch(()=>{});
if(session){api('/api/me').then(r=>{name=r.name;if(r.role==='admin')admin();else home()}).catch(()=>login())}else login();
