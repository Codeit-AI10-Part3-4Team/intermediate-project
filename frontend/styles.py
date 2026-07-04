# frontend/styles.py
# CSS for the single-page chat UI (design spec v2 — tokens: frontend/design/tokens.css).
# Selectors use data-testid only; st-emotion-cache-* class names are build-specific
# and break across Streamlit upgrades. Colors are duplicated from tokens.css on
# purpose (Streamlit does not expose CSS custom properties to injected styles).

BASE_CSS = """
<style>
header[data-testid="stHeader"] { display: none; }

/* chat messages: no avatars, assistant as plain text, user as right bubble */
[data-testid="stChatMessageAvatarUser"],
[data-testid="stChatMessageAvatarAssistant"] { display: none; }
[data-testid="stChatMessage"] { background: transparent; padding: 0.25rem 0; }
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
  margin-left: auto; width: fit-content; max-width: 70%;
  background: #E4E8D5; border-radius: 16px 16px 4px 16px; padding: 0.5rem 1.1rem;
}

/* chat input: white pill, 2.5em min height, green focus ring */
[data-testid="stChatInput"] {
  background: #FFFFFF; border: 1.5px solid #DFE0D4; border-radius: 18px;
  box-shadow: 0 1px 2px rgba(44, 51, 35, .06);
}
[data-testid="stChatInput"]:focus-within {
  border-color: #8C9963; box-shadow: 0 0 0 3px rgba(140, 153, 99, .18);
}
[data-testid="stChatInput"] textarea { min-height: 2.5em; }

/* file uploader compacted into a centered "문서 업로드" ghost button.
   The label swap (font-size:0 + ::after) is the one fragile text hack here:
   if a Streamlit upgrade breaks it, the button falls back to "Browse files"
   but keeps working. */
[data-testid="stFileUploaderDropzoneInstructions"] { display: none; }
[data-testid="stFileUploaderDropzone"] {
  background: transparent; border: 0; padding: 0; min-height: 0;
  display: flex; justify-content: center;
}
[data-testid="stFileUploaderDropzone"] button {
  font-size: 0; line-height: 1;
  background: #FFFFFF; color: #2C3323; border: 1px solid #DFE0D4;
  border-radius: 12px; padding: 0.7rem 1.3rem;
}
/* some Streamlit versions render the label inside child nodes (icon + span)
   that keep their own font-size — hide them so only ::after shows */
[data-testid="stFileUploaderDropzone"] button > * { display: none; }
[data-testid="stFileUploaderDropzone"] button::after {
  content: "문서 업로드"; font-size: 15px; font-weight: 700;
}
[data-testid="stFileUploaderDropzone"] button:hover {
  border-color: #8C9963; color: #57633F;
}

.oop-greeting {
  text-align: center; font-size: 26px; font-weight: 800; letter-spacing: -.2px;
  display: flex; flex-direction: column; align-items: center; gap: 6px;
}
.oop-greeting-sub { font-size: 17px; font-weight: 400; color: #6A7060; }
.oop-checking { flex-direction: row; gap: 12px; font-size: 22px; }
.oop-cap { font-size: 13px; color: #6A7060; text-align: center; }
.oop-badge {
  display: inline-flex; align-items: center; gap: 7px; border-radius: 999px;
  padding: 7px 14px; font-size: 13px; font-weight: 700; line-height: 1;
}
.oop-badge::before { content: ""; width: 8px; height: 8px; border-radius: 50%;
  background: currentColor; }
.oop-badge.pass { background: #E9EBDF; color: #57633F; }
.oop-badge.fail { background: #F6E4DF; color: #B4533C; }
.oop-spinner {
  width: 26px; height: 26px; border-radius: 50%; flex: none;
  border: 3px solid #E9EBDF; border-top-color: #8C9963;
  animation: oop-spin .9s linear infinite;
}
@keyframes oop-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) {
  .oop-spinner { animation: none; border-top-color: #57633F; }
}
.oop-genwrap {
  display: flex; flex-direction: column; align-items: center; gap: 10px;
  padding: 2.5rem 0;
}
</style>
"""

HOME_CSS = """
<style>
[data-testid="stMainBlockContainer"] { padding-top: 1.5rem; padding-bottom: 0.5rem; }
/* Vertically center the UI group: the top-level vertical block fills the
   viewport and the .oop-vspace spacers (flex-grow) absorb the leftover
   space above and below the group. */
[data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlock"] {
  min-height: calc(100vh - 2rem);
}
[data-testid="stElementContainer"]:has(.oop-vspace) { flex: 1 1 0; }
</style>
"""

CHAT_CSS = """
<style>
[data-testid="stMainBlockContainer"] { padding-top: 1.5rem; padding-bottom: 1rem; }
[data-testid="stBottomBlockContainer"] { max-width: 52rem; margin: 0 auto; }
</style>
"""
