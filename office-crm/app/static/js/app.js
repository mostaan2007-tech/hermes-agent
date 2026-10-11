/* Small, dependency-free behaviour layer for the office system.
   Everything here is progressive enhancement: every feature still works with
   JavaScript disabled (forms post normally, boards have a status selector). */
(function () {
  "use strict";

  var csrf = function () {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.content : "";
  };

  /* ------------------------------------------------ CSRF on plain forms */
  document.addEventListener(
    "submit",
    function (event) {
      var form = event.target;
      if (!form || form.tagName !== "FORM") return;
      if (form.querySelector('input[name="csrf_token"]')) return;
      var input = document.createElement("input");
      input.type = "hidden";
      input.name = "csrf_token";
      input.value = csrf();
      form.appendChild(input);
    },
    true
  );

  /* --------------------------------------------------- row click to open */
  document.addEventListener("click", function (event) {
    var row = event.target.closest("[data-href]");
    if (!row) return;
    if (event.target.closest("a, button, input, select, form")) return;
    window.location = row.getAttribute("data-href");
  });

  /* -------------------------------------------------- htmx error toasts */
  document.addEventListener("htmx:responseError", function (event) {
    var status = event.detail.xhr ? event.detail.xhr.status : 0;
    var text = status === 403 ? "دسترسی مجاز نیست یا نشانه امنیتی منقضی شده است." : "خطا در انجام عملیات.";
    alert(text);
  });

  /* --------------------------------------------------------- Alpine bits */
  document.addEventListener("alpine:init", function () {
    var Alpine = window.Alpine;
    if (!Alpine) return;

    Alpine.data("multiSelect", function (initial) {
      return {
        selected: initial || [],
        options: {},
        init: function () {
          var holder = this.$el.querySelector("script[data-options]");
          if (!holder) return;
          try {
            this.options = Object.fromEntries(JSON.parse(holder.textContent));
          } catch (error) {
            this.options = {};
          }
        },
        labelOf: function (id) {
          return this.options[id] || id;
        },
        add: function (value) {
          if (!value) return;
          var numeric = Number(value);
          if (this.selected.indexOf(numeric) === -1) this.selected.push(numeric);
        },
        remove: function (id) {
          this.selected = this.selected.filter(function (item) {
            return item !== id;
          });
        },
      };
    });

    /* quotation / invoice line items */
    Alpine.data("quoteForm", function (config) {
      return {
        items: config.items || [],
        products: config.products || [],
        currency: config.currency || "",
        discount: config.discount || 0,
        taxRate: config.taxRate || 0,
        init: function () {
          if (!this.items.length) this.addRow();
        },
        addRow: function () {
          this.items.push({ product_id: "", description: "", quantity: 1, unit: "", unit_price: 0, discount: 0 });
        },
        removeRow: function (index) {
          this.items.splice(index, 1);
          if (!this.items.length) this.addRow();
        },
        fill: function (index) {
          var row = this.items[index];
          var product = this.products.find(function (item) {
            return String(item.id) === String(row.product_id);
          });
          if (product) {
            row.description = product.name;
            row.unit = product.unit || "";
            row.unit_price = product.price || 0;
          }
        },
        rowTotal: function (row) {
          var value = (Number(row.quantity) || 0) * (Number(row.unit_price) || 0) - (Number(row.discount) || 0);
          return Math.max(0, value);
        },
        get subtotal() {
          return this.items.reduce((sum, row) => sum + this.rowTotal(row), 0);
        },
        get taxAmount() {
          return Math.round(Math.max(0, this.subtotal - Number(this.discount || 0)) * Number(this.taxRate || 0) / 100);
        },
        get total() {
          return Math.max(0, this.subtotal - Number(this.discount || 0)) + this.taxAmount;
        },
        fa: function (value) {
          return Number(value || 0).toLocaleString("fa-IR");
        },
        submit: function (event) {
          var payload = document.getElementById("items-json");
          if (payload) {
            payload.value = JSON.stringify(
              this.items.filter(function (row) {
                return row.description && row.description.trim();
              })
            );
          }
        },
      };
    });

    /* ordered picker: signature chains, copy lists, any "pick these, in this order" */
    Alpine.data("orderPicker", function (initial, options, field, ordered) {
      return {
        selected: (initial || []).map(String),
        options: options || [],
        field: field || "ids",
        ordered: ordered !== false,
        labelOf: function (id) {
          var person = this.options.find(function (item) {
            return String(item.id) === String(id);
          });
          return person ? person.name : id;
        },
        add: function (value) {
          if (!value) return;
          var id = String(value);
          if (this.selected.indexOf(id) === -1) this.selected.push(id);
        },
        remove: function (id) {
          this.selected = this.selected.filter(function (item) {
            return String(item) !== String(id);
          });
        },
        move: function (index, delta) {
          if (!this.ordered) return;
          var target = index + delta;
          if (target < 0 || target >= this.selected.length) return;
          var copy = this.selected.slice();
          var moved = copy.splice(index, 1)[0];
          copy.splice(target, 0, moved);
          this.selected = copy;
        },
        fa: function (value) {
          try {
            return Number(value).toLocaleString("fa-IR");
          } catch (error) {
            return value;
          }
        },
      };
    });

    /* generic confirmation for destructive actions */
    Alpine.data("confirmable", function () {
      return {
        ask: function (event, message) {
          if (!window.confirm(message || "از انجام این عملیات مطمئن هستید؟")) event.preventDefault();
        },
      };
    });
  });

  /* ------------------------------------------------------------- kanban  */
  function moveCard(card, column) {
    var dealId = card.getAttribute("data-deal-id");
    var stageId = column.getAttribute("data-stage-id");
    if (!dealId || !stageId) return;
    card.classList.add("opacity-50");
    var body = new FormData();
    body.append("stage_id", stageId);
    fetch("/deals/" + dealId + "/stage", {
      method: "POST",
      body: body,
      headers: { "X-CSRF-Token": csrf() },
      credentials: "same-origin",
    })
      .then(function (response) {
        if (response.ok || response.redirected) {
          window.location.reload();
        } else {
          alert("تغییر مرحله ناموفق بود.");
          card.classList.remove("opacity-50");
        }
      })
      .catch(function () {
        alert("ارتباط با سرور برقرار نشد.");
        card.classList.remove("opacity-50");
      });
  }

  function initKanban(root) {
    var cards = (root || document).querySelectorAll("[data-deal-id]");
    var columns = (root || document).querySelectorAll("[data-stage-id]");
    if (!cards.length) return;

    cards.forEach(function (card) {
      card.setAttribute("draggable", "true");
      card.addEventListener("dragstart", function (event) {
        event.dataTransfer.setData("text/plain", card.getAttribute("data-deal-id"));
        card.classList.add("dragging");
      });
      card.addEventListener("dragend", function () {
        card.classList.remove("dragging");
      });
    });

    columns.forEach(function (column) {
      column.addEventListener("dragover", function (event) {
        event.preventDefault();
        column.classList.add("kanban-over");
      });
      column.addEventListener("dragleave", function () {
        column.classList.remove("kanban-over");
      });
      column.addEventListener("drop", function (event) {
        event.preventDefault();
        column.classList.remove("kanban-over");
        var dealId = event.dataTransfer.getData("text/plain");
        var card = document.querySelector('[data-deal-id="' + dealId + '"]');
        if (card) moveCard(card, column);
      });
    });
  }

  /* task board uses the same drag & drop, with a status endpoint */
  function initTaskBoard(root) {
    var board = (root || document).querySelector("[data-task-board]");
    if (!board) return;
    board.querySelectorAll("[data-task-id]").forEach(function (card) {
      card.setAttribute("draggable", "true");
      card.addEventListener("dragstart", function (event) {
        event.dataTransfer.setData("text/plain", card.getAttribute("data-task-id"));
        card.classList.add("dragging");
      });
      card.addEventListener("dragend", function () {
        card.classList.remove("dragging");
      });
    });
    board.querySelectorAll("[data-task-status]").forEach(function (column) {
      column.addEventListener("dragover", function (event) {
        event.preventDefault();
        column.classList.add("kanban-over");
      });
      column.addEventListener("dragleave", function () {
        column.classList.remove("kanban-over");
      });
      column.addEventListener("drop", function (event) {
        event.preventDefault();
        column.classList.remove("kanban-over");
        var taskId = event.dataTransfer.getData("text/plain");
        var card = document.querySelector('[data-task-id="' + taskId + '"]');
        if (!card) return;
        var body = new FormData();
        body.append("status", column.getAttribute("data-task-status"));
        body.append("next", window.location.pathname + window.location.search);
        card.classList.add("opacity-50");
        fetch("/tasks/" + taskId + "/status", {
          method: "POST",
          body: body,
          headers: { "X-CSRF-Token": csrf() },
          credentials: "same-origin",
        })
          .then(function (response) {
            if (response.ok || response.redirected) window.location.reload();
            else {
              alert("تغییر وضعیت ناموفق بود.");
              card.classList.remove("opacity-50");
            }
          })
          .catch(function () {
            alert("ارتباط با سرور برقرار نشد.");
            card.classList.remove("opacity-50");
          });
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    initKanban(document);
    initTaskBoard(document);
  });
  document.addEventListener("htmx:afterSwap", function (event) {
    initKanban(event.target);
    initTaskBoard(event.target);
  });

  /* print buttons */
  document.addEventListener("click", function (event) {
    var trigger = event.target.closest("[data-print]");
    if (trigger) {
      event.preventDefault();
      window.print();
    }
  });
})();
