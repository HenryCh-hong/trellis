const input = document.getElementById("api");
chrome.storage.local.get("apiBase").then(({ apiBase }) => {
  input.value = apiBase || "http://127.0.0.1:8000";
});
document.getElementById("save").addEventListener("click", async () => {
  await chrome.storage.local.set({ apiBase: input.value.trim() });
  document.getElementById("saved").textContent = "Saved.";
});
