/* Activates the Jalali date picker on every input marked with data-jdp.
   Persian users can also simply type ۱۴۰۵/۰۷/۱۹ — the server parses both. */
(function () {
  "use strict";

  function boot() {
    if (!window.jalaliDatepicker) return;
    try {
      window.jalaliDatepicker.startWatch({
        selector: "input[data-jdp]",
        initDate: "today",
        autoClose: true,
        showHint: true,
      });
    } catch (error) {
      /* the library version in this build watches by attribute only */
      try {
        window.jalaliDatepicker.startWatch();
      } catch (inner) {
        console.warn("date picker unavailable", inner);
      }
    }
  }

  document.addEventListener("DOMContentLoaded", boot);
  document.addEventListener("htmx:afterSwap", boot);
})();
