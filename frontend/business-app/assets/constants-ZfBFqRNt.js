const l=[{v:"bar",l:"Bar"},{v:"ristorante",l:"Ristorante"},{v:"hotel",l:"Hotel"},{v:"palestra",l:"Palestra"},{v:"coworking",l:"Coworking"},{v:"ufficio",l:"Ufficio"},{v:"scuola",l:"Scuola"},{v:"negozio",l:"Negozio"},{v:"altro",l:"Altro"}],n=i=>{var e;return((e=l.find(a=>a.v===i))==null?void 0:e.l)||"Attività"},c={bar:"☕",ristorante:"🍽️",hotel:"🏨",palestra:"🏋️",coworking:"💼",ufficio:"🏢",scuola:"🎓",negozio:"🛍️",altro:"📍"},s=["Titolare","Manager","Responsabile marketing","Dipendente","Altro"],u=["Visibilità","Plastic free","Refill","Qualità acqua","Profilo verificato","Analisi acqua future","Dashboard analytics"],t=[{key:"new",label:"Nuove richieste",color:"#0ea5e9"},{key:"to_complete",label:"Profilo da completare",color:"#6366f1"},{key:"review",label:"Revisione contenuti",color:"#8b5cf6"},{key:"badge",label:"Verifica e badge",color:"#d946ef"},{key:"publish",label:"Pubblicazione",color:"#f59e0b"},{key:"access",label:"Accesso Business",color:"#10b981"},{key:"active",label:"Dashboard attiva",color:"#16a34a"},{key:"premium",label:"Analisi / Premium",color:"#475569"}],d=i=>t.find(e=>e.key===i)||t[0],p=[{key:"verified",label:"AcquaMap Verified",color:"#16a34a",icon:"✓"},{key:"water_experience",label:"Water Experience",color:"#0492cf",icon:"💧"},{key:"lab_quality",label:"Lab Quality",color:"#7c3aed",icon:"🧪"},{key:"business_premium",label:"Business Premium",color:"#f59e0b",icon:"◆"}],m={draft:"Bozza",in_review:"In revisione",changes_requested:"Modifiche richieste",approved:"Approvato",published:"Pubblicato",suspended:"Sospeso",archived:"Archiviato"},v={view:"Visualizzazioni",open_map:"Aperture mappa",click_phone:"Click telefono",click_maps:"Click indicazioni",click_website:"Click sito",click_instagram:"Click Instagram",click_whatsapp:"Click WhatsApp",open_gallery:"Aperture gallery"};function r(i={}){const e=i.water_info||{},a=i.extra||{},o=[i.business_name,i.category,i.address,i.city,i.phone,i.description,a.long_desc,a.hours&&Object.keys(a.hours).length,a.services&&a.services.length,e.water_type&&e.water_type.length||a.water&&Object.values(a.water).some(Boolean),i.logo_url,i.cover_image_url,i.latitude!=null&&i.longitude!=null];return Math.round(o.filter(Boolean).length/o.length*100)}function f(i={}){let e=r(i)*.4;return i.verification_status&&i.verification_status!=="not_verified"&&(e+=20),i.logo_url&&i.cover_image_url&&(e+=10),e+=Math.min(20,(i.badges||[]).length*7),i.latitude!=null&&i.longitude!=null&&(e+=10),Math.round(Math.min(100,e))}const b=`Informativa sul trattamento dei dati personali — AcquaMap Business

Titolare del trattamento
Il titolare del trattamento è AcquaMap / Hydroroma. Per qualsiasi richiesta relativa ai tuoi dati puoi scrivere a acquamap@hydroroma.com.

Finalità del trattamento
I dati forniti tramite questo modulo di candidatura sono trattati per: (a) valutare la richiesta di adesione al programma AcquaMap Business Expand; (b) contattare il referente indicato; (c) creare, previa approvazione, un profilo pubblico dell'attività su AcquaMap; (d) gestire la collaborazione, le comunicazioni di servizio e l'eventuale assistenza.

Base giuridica
Il trattamento si fonda sul consenso dell'interessato e sull'esecuzione di misure precontrattuali richieste dall'interessato.

Categorie di dati
Dati identificativi dell'attività e del referente, dati di contatto, informazioni commerciali e relative ai servizi (incluse informazioni sull'acqua), eventuali immagini caricate.

Dati pubblicati
In caso di approvazione e con il tuo consenso esplicito, alcuni dati dell'attività (nome, categoria, indirizzo, contatti pubblici, descrizione, foto, servizi e informazioni sull'acqua) saranno resi pubblici sul profilo AcquaMap. I dati del referente NON sono pubblicati e restano riservati al team AcquaMap.

Comunicazioni commerciali
Con apposito e separato consenso, i dati di contatto potranno essere usati per comunicazioni relative al programma e a funzionalità future (incluse analisi dell'acqua e piani premium).

Conservazione
I dati sono conservati per il tempo necessario alle finalità indicate e, in caso di mancata approvazione, per un periodo limitato a fini di verifica e contatto, salvo richiesta di cancellazione.

Diritti dell'interessato
Hai diritto di accesso, rettifica, cancellazione, limitazione, opposizione e portabilità dei dati, oltre al diritto di revocare il consenso in qualsiasi momento e di proporre reclamo all'autorità di controllo.

Veridicità dei dati
Dichiarando di accettare, confermi che i dati inseriti sono veritieri e che sei autorizzato a fornirli per conto dell'attività indicata.

Scorrendo fino in fondo e accettando, dichiari di aver letto e compreso la presente informativa.

— Fine dell'informativa —`;export{t as A,p as B,l as C,v as E,b as P,s as R,u as a,r as b,n as c,m as d,f as e,c as f,d as s};
