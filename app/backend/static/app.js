(function(){
  function tick(){
    const el=document.getElementById('clock');
    if(el) el.textContent=new Date().toLocaleTimeString('it-IT',{hour:'2-digit',minute:'2-digit',second:'2-digit'});
  }
  tick(); setInterval(tick,1000);
})();
