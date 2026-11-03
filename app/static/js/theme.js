/* Niezapominajka – motyw jasny/ciemny ustawiany przed narysowaniem strony (osobny plik ze względu na CSP). */
try { var t = localStorage.getItem("nz-theme") || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"); document.documentElement.dataset.theme = t; } catch (e) {}
