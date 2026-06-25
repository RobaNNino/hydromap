import { createClient } from "@supabase/supabase-js";

// Config pubblica (publishable key): sicura nel browser. La sicurezza è data
// dalla RLS Supabase + dalla verifica JWT lato Flask.
const SUPABASE_URL = "https://bzzbgtxlpwecqfydbguy.supabase.co";
const SUPABASE_PUBLISHABLE_KEY = "sb_publishable_rPLQi9Swf8d4vzzYSocSQA_3JxZQ25N";

export const supabase = createClient(SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY, {
  auth: { persistSession: true, autoRefreshToken: true },
});

export async function getAccessToken() {
  const { data } = await supabase.auth.getSession();
  return data?.session?.access_token || "";
}
