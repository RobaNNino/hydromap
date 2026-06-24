/* Config Supabase per il browser. SOLO valori PUBBLICI:
   la publishable key è progettata per stare nel frontend (la sicurezza è data
   dalla RLS + dalla verifica JWT lato Flask). La SECRET key non va MAI qui. */
window.SUPABASE_CONFIG = {
  url: "https://bzzbgtxlpwecqfydbguy.supabase.co",
  publishableKey: "sb_publishable_rPLQi9Swf8d4vzzYSocSQA_3JxZQ25N",
};
