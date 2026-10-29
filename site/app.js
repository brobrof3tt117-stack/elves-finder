(function () {
  "use strict";

  var YEAR_COLORS = { 2015: "#8a6fc7", 2016: "#3b8fc2", 2017: "#e2763b", 2018: "#6f9e3b" };

  function el(id) { return document.getElementById(id); }

  function esc(text) {
    return String(text == null ? "" : text)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function safeUrl(url) {
    return typeof url === "string" && url.indexOf("https://") === 0 ? url : "";
  }

  function dollars(n) {
    return "$" + Number(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function total(item) { return item.price + (item.shipping || 0); }

  function timeAgo(iso) {
    var mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
    if (mins < 1) return "just now";
    if (mins < 60) return mins + (mins === 1 ? " minute ago" : " minutes ago");
    var hrs = Math.round(mins / 60);
    if (hrs < 48) return hrs + (hrs === 1 ? " hour ago" : " hours ago");
    var days = Math.round(hrs / 24);
    return days + " days ago";
  }

  function timeLeft(iso) {
    var ms = new Date(iso).getTime() - Date.now();
    if (ms <= 0) return null;
    var mins = Math.floor(ms / 60000);
    var d = Math.floor(mins / 1440);
    var h = Math.floor((mins % 1440) / 60);
    var m = mins % 60;
    if (d > 0) return d + "d " + h + "h left";
    if (h > 0) return h + "h " + m + "m left";
    return m + "m left";
  }

  function stillOpen(item) {
    return item.kind !== "Auction" || !item.ends || new Date(item.ends).getTime() > Date.now();
  }

  function loadJson(path) {
    return fetch(path + "?t=" + Date.now(), { cache: "no-store" }).then(function (r) {
      if (!r.ok) throw new Error(path + " returned " + r.status);
      return r.json();
    });
  }

  function placeholder(number) {
    return '<span class="ph">' + esc(number) + "</span>";
  }

  function thumbHtml(url, alt, number) {
    var safe = safeUrl(url);
    return safe
      ? '<img src="' + esc(safe) + '" alt="' + esc(alt) + '" loading="lazy" referrerpolicy="no-referrer">'
      : placeholder(number);
  }

  function showStatus(data) {
    var banner = el("banner");
    var updated = el("updated");
    if (data.updated) {
      updated.textContent = "Listings updated " + timeAgo(data.updated) + ". They refresh about every hour.";
    } else {
      updated.textContent = "Waiting for the first update.";
    }
    var html = "";
    if (data.status === "waiting") {
      html = '<div class="banner"><strong>The first update has not finished yet.</strong>Check back in a few minutes. If this message stays for more than an hour, follow the "Fixing problems" part of the setup guide.</div>';
    } else if (data.status === "needs_keys") {
      html = '<div class="banner"><strong>Almost there: the eBay keys are missing.</strong>Add EBAY_CLIENT_ID and EBAY_CLIENT_SECRET in your GitHub repository settings (Step 4 of the setup guide).</div>';
    } else if (data.status === "bad_keys") {
      html = '<div class="banner bad"><strong>eBay did not accept the keys.</strong>Copy the Production App ID and Cert ID from the eBay developer site again and paste them into the GitHub secrets (Step 4 of the setup guide).</div>';
    } else if (data.updated && Date.now() - new Date(data.updated).getTime() > 4 * 3600 * 1000) {
      html = '<div class="banner"><strong>These listings are more than 4 hours old.</strong>The hourly update may be paused. Some of these items could already be sold.</div>';
    }
    banner.innerHTML = html;
    var rules = data.rules || {};
    if (rules.min_seller_positive_percent != null) {
      el("foot").textContent =
        "Shows only listings marked New (factory sealed) from US sellers with at least " +
        rules.min_seller_positive_percent + "% positive feedback and " + rules.min_seller_ratings +
        " ratings. Titles that mention opened, used, incomplete or bundled items are hidden. Always read the listing before you buy. Set pictures come from the LEGO Wiki on Fandom." +
        (rules.shipping_for_zip ? " Shipping prices are what eBay quotes for delivery to your ZIP code." : "");
    }
  }

  function setSummary(entry) {
    var items = (entry && entry.listings ? entry.listings : []).filter(stillOpen);
    var lowest = null;
    items.forEach(function (it) { if (lowest === null || total(it) < lowest) lowest = total(it); });
    var image = null;
    for (var i = 0; i < items.length && !image; i += 1) image = safeUrl(items[i].image);
    return { items: items, lowest: lowest, image: image, error: !!(entry && entry.error) };
  }

  /* Official box picture from the LEGO Fandom wiki, or an eBay photo if there is none */
  function boxPicture(data, s, sum) {
    var official = data.images && safeUrl(data.images[s.number]);
    return official || sum.image;
  }

  /* Budget */

  function todayIn(zone) {
    // Today's date (YYYY-MM-DD) in the given time zone, so Friday means Friday in Eastern time.
    try {
      return new Intl.DateTimeFormat("en-CA", { timeZone: zone, year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
    } catch (e) {
      var d = new Date();
      return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
    }
  }

  function dayNumber(ymd) {
    var p = ymd.split("-");
    return Date.UTC(+p[0], +p[1] - 1, +p[2]) / 86400000;
  }

  function niceDate(ymd) {
    var p = ymd.split("-");
    return new Date(Date.UTC(+p[0], +p[1] - 1, +p[2])).toLocaleDateString("en-US",
      { timeZone: "UTC", weekday: "long", month: "short", day: "numeric" });
  }

  function computeBudget(cfg, purchases) {
    var today = todayIn(cfg.time_zone || "America/New_York");
    var first = cfg.first_weekly_add;
    var weeks = 0;
    var diff = dayNumber(today) - dayNumber(first);
    if (diff >= 0) weeks = Math.floor(diff / 7) + 1;
    var added = Number(cfg.starting_amount) + weeks * Number(cfg.weekly_amount);
    var spent = 0;
    purchases.forEach(function (p) { spent += Number(p.paid) || 0; });
    var nextDay = dayNumber(first) + weeks * 7;
    var next = new Date(nextDay * 86400000).toISOString().slice(0, 10);
    return {
      added: added, spent: Math.round(spent * 100) / 100,
      left: Math.round((added - spent) * 100) / 100,
      weekly: Number(cfg.weekly_amount), next: next
    };
  }

  function ownedMap(purchases) {
    var m = {};
    purchases.forEach(function (p) { (m[p.set] = m[p.set] || []).push(p); });
    return m;
  }

  function showBudget(b, purchasesOk) {
    var box = el("budget");
    if (!box) return;
    var pct = b.added > 0 ? Math.max(0, Math.min(100, (b.spent / b.added) * 100)) : 0;
    box.innerHTML =
      '<div class="budget-top"><span class="budget-label">Budget left</span>' +
      '<span class="budget-left' + (b.left < 0 ? " over" : "") + '">' + dollars(b.left) + "</span></div>" +
      '<div class="budget-bar" role="img" aria-label="' + dollars(b.spent) + " spent of " + dollars(b.added) + '">' +
      '<span style="width:' + pct.toFixed(1) + '%"></span></div>' +
      '<div class="budget-sub">' + dollars(b.spent) + " spent of " + dollars(b.added) + " so far. Next +" +
      dollars(b.weekly) + " on " + niceDate(b.next) + ".</div>" +
      (purchasesOk ? "" : '<div class="budget-sub warn">Purchases could not be loaded in the last update, so this may be too high.</div>');
  }

  /* Home page */

  function renderHome(sets, data, budget, owned) {
    var q = el("q");
    var only = el("onlyForSale");

    function draw() {
      var term = q.value.trim().toLowerCase();
      var byYear = {};
      sets.forEach(function (s) {
        var sum = setSummary(data.sets[s.number]);
        if (only.checked && sum.items.length === 0) return;
        if (term && (s.name + " " + s.number + " " + s.kind).toLowerCase().indexOf(term) === -1) return;
        (byYear[s.year] = byYear[s.year] || []).push({ s: s, sum: sum });
      });
      var years = Object.keys(byYear).sort();
      if (years.length === 0) {
        el("years").innerHTML = '<p class="empty">No sets match. Clear the search box or untick "Only show sets for sale".</p>';
        return;
      }
      el("years").innerHTML = years.map(function (y) {
        var rows = byYear[y];
        var forSale = rows.filter(function (r) { return r.sum.items.length > 0; }).length;
        return '<section class="year" style="border-top-color:' + (YEAR_COLORS[y] || "#2f6b4f") + '">' +
          "<h2>" + esc(y) + "</h2>" +
          '<p class="count">' + forSale + " of " + rows.length + " for sale right now</p>" +
          '<div class="grid">' + rows.map(tileHtml).join("") + "</div></section>";
      }).join("");
    }

    function tileHtml(row) {
      var s = row.s, sum = row.sum;
      var sale;
      if (sum.error) sale = '<span class="sale none">Could not check this hour</span>';
      else if (sum.items.length === 0) sale = '<span class="sale none">None for sale right now</span>';
      else sale = '<span class="sale">' + sum.items.length + " for sale, from " + dollars(sum.lowest) + "</span>";
      var orig = s.retail ? '<span class="orig">Original price ' + dollars(s.retail) + "</span>" : '<span class="orig">Free gift, no original price</span>';
      var kind = s.kind !== "Set" ? '<span class="kind">' + esc(s.kind) + "</span>" : "";
      var cls = "tile", badge = "";
      if (owned[s.number]) {
        cls += " owned";
        badge = '<span class="badge owned-badge">She owns this</span>';
      } else if (sum.lowest !== null && sum.lowest <= budget.left) {
        cls += " afford";
        badge = '<span class="badge afford-badge">She can afford this</span>';
      }
      return '<a class="' + cls + '" href="set.html?set=' + encodeURIComponent(s.number) + '">' + badge +
        '<div class="thumb" data-num="' + esc(s.number) + '">' + thumbHtml(boxPicture(data, s, sum), s.name, s.number) + "</div>" +
        '<div class="body"><span class="num">Set ' + esc(s.number) + "</span>" +
        "<h3>" + esc(s.name) + "</h3>" + kind + sale + orig + "</div></a>";
    }

    q.addEventListener("input", draw);
    only.addEventListener("change", draw);
    draw();
  }

  /* Set page */

  function renderSet(sets, data, budget, owned) {
    var number = new URLSearchParams(location.search).get("set");
    var s = null;
    sets.forEach(function (x) { if (x.number === number) s = x; });
    if (!s) {
      el("hero").innerHTML = '<div><h1>Set not found</h1><p>Go back to the list and pick a set.</p></div>';
      return;
    }
    document.title = s.name + " (" + s.number + ") | Sealed Elves Finder";
    var sum = setSummary(data.sets[s.number]);
    var heroImg = boxPicture(data, s, sum);

    el("hero").innerHTML =
      '<div class="thumb" data-num="' + esc(s.number) + '">' + thumbHtml(heroImg, s.name, s.number) + "</div>" +
      "<div><h1>" + esc(s.name) + "</h1>" +
      '<ul class="facts">' +
      "<li><span>Set number</span><b>" + esc(s.number) + "</b></li>" +
      "<li><span>Released</span><b>" + esc(s.year) + "</b></li>" +
      "<li><span>Original price</span><b>" + (s.retail ? dollars(s.retail) : "Free gift") + "</b></li>" +
      "<li><span>Sealed for sale</span><b>" + sum.items.length + "</b></li>" +
      (sum.lowest !== null ? "<li><span>Lowest total</span><b>" + dollars(sum.lowest) + "</b></li>" : "") +
      "</ul>" + ownedNote(owned[s.number]) + "</div>";

    var show = "all";
    var sortSel = el("sort");

    function draw() {
      var items = sum.items.filter(function (it) { return show === "all" || it.kind === show; });
      var mode = sortSel.value;
      items.sort(function (a, b) {
        if (mode === "high") return total(b) - total(a);
        if (mode === "ending") {
          var ae = a.ends ? new Date(a.ends).getTime() : Infinity;
          var be = b.ends ? new Date(b.ends).getTime() : Infinity;
          return ae === be ? total(a) - total(b) : ae - be;
        }
        if (mode === "newest") {
          var al = a.listed ? new Date(a.listed).getTime() : 0;
          var bl = b.listed ? new Date(b.listed).getTime() : 0;
          return bl - al;
        }
        return total(a) - total(b);
      });

      if (sum.error) {
        el("list").innerHTML = '<p class="empty">eBay did not answer for this set during the last update. It will try again within the hour.</p>';
        return;
      }
      if (sum.items.length === 0) {
        el("list").innerHTML = '<p class="empty">No sealed copies from trusted US sellers are listed right now. This page checks again every hour.</p>';
        return;
      }
      if (items.length === 0) {
        el("list").innerHTML = '<p class="empty">None of that type right now. Pick "All" to see every listing.</p>';
        return;
      }
      el("list").innerHTML = items.map(function (it) { return itemHtml(it, s, budget, !!owned[s.number]); }).join("");
    }

    el("filters").hidden = sum.items.length === 0;
    Array.prototype.forEach.call(document.querySelectorAll(".seg button"), function (btn) {
      btn.addEventListener("click", function () {
        show = btn.getAttribute("data-show");
        Array.prototype.forEach.call(document.querySelectorAll(".seg button"), function (b) {
          b.setAttribute("aria-pressed", b === btn ? "true" : "false");
        });
        draw();
      });
    });
    sortSel.addEventListener("change", draw);
    draw();
  }

  function ownedNote(list) {
    if (!list) return "";
    return '<p class="owned-note">She already owns this set. ' + list.map(function (p) {
      return "Bought " + (p.date ? "on " + esc(p.date) + " " : "") + "for " + dollars(p.paid) + ".";
    }).join(" ") + "</p>";
  }

  function itemHtml(it, s, budget, isOwned) {
    var tags = [];
    var fits = !isOwned && it.shipping !== null && it.shipping !== undefined && total(it) <= budget.left;
    if (fits) tags.push('<span class="tag fits">Within budget</span>');
    if (it.kind === "Auction") {
      var left = it.ends ? timeLeft(it.ends) : null;
      tags.push('<span class="tag auction">Auction, ' + it.bids + (it.bids === 1 ? " bid" : " bids") + (left ? ", " + left : "") + "</span>");
    } else {
      tags.push('<span class="tag">Buy It Now' + (it.best_offer ? " or Best Offer" : "") + "</span>");
    }
    if (it.box_note) tags.push('<span class="tag warn">Box damage mentioned</span>');
    if (it.listed && Date.now() - new Date(it.listed).getTime() < 48 * 3600 * 1000) tags.push('<span class="tag">Listed in the last 2 days</span>');

    var ship;
    if (it.shipping === null || it.shipping === undefined) ship = "Shipping shown at checkout";
    else if (it.shipping === 0) ship = "Free shipping";
    else ship = "plus " + dollars(it.shipping) + " shipping";

    var vs = "";
    if (s.retail) {
      var pct = Math.round((total(it) / s.retail - 1) * 100);
      if (pct > 0) vs = '<div class="vs up">' + pct + "% above original " + dollars(s.retail) + "</div>";
      else if (pct < 0) vs = '<div class="vs down">' + Math.abs(pct) + "% below original " + dollars(s.retail) + "</div>";
      else vs = '<div class="vs">Same as original price</div>';
    }

    var seller = it.seller_percent != null
      ? '<div class="seller">Seller: ' + esc(it.seller_percent) + "% positive from " + Number(it.seller_ratings).toLocaleString("en-US") + " ratings</div>"
      : "";

    return '<article class="item' + (fits ? " fits" : "") + '">' +
      '<div class="thumb" data-num="' + esc(s.number) + '">' + thumbHtml(it.image, it.title, s.number) + "</div>" +
      "<div><h3>" + esc(it.title) + "</h3>" +
      '<div class="tags">' + tags.join("") + "</div>" + seller + "</div>" +
      '<div class="price"><div class="big">' + dollars(it.price) + "</div>" +
      '<div class="ship">' + ship + "</div>" + vs +
      '<a class="buy" href="' + esc(safeUrl(it.url)) + '" target="_blank" rel="noopener noreferrer">View on eBay</a></div>' +
      "</article>";
  }

  /* Add a purchase page */

  function repoName(purchasesData) {
    if (purchasesData.repo && /^[\w.-]+\/[\w.-]+$/.test(purchasesData.repo)) return purchasesData.repo;
    var owner = location.hostname.split(".")[0];
    var repo = location.pathname.split("/").filter(Boolean)[0] || "";
    return owner + "/" + repo;
  }

  function renderAdd(sets, data, budget, owned, purchasesData) {
    var sel = el("pSet");
    sel.innerHTML = '<option value="">Pick a set</option>' + sets.map(function (s) {
      return '<option value="' + esc(s.number) + '">' + esc(s.number + " " + s.name) + (owned[s.number] ? " (owned)" : "") + "</option>";
    }).join("");
    el("pDate").value = todayIn("America/New_York");
    var repo = repoName(purchasesData);

    el("addForm").addEventListener("submit", function (e) {
      e.preventDefault();
      var msg = el("addMsg");
      var num = sel.value;
      var paid = parseFloat(String(el("pPaid").value).replace(/[$,\s]/g, ""));
      var date = el("pDate").value;
      if (!num) { msg.className = "form-msg bad"; msg.textContent = "Pick which set she bought."; return; }
      if (!(paid >= 0) || paid > 100000) { msg.className = "form-msg bad"; msg.textContent = "Type the total paid, like 64.99."; return; }
      var s = sets.filter(function (x) { return x.number === num; })[0];
      var title = "Purchase: " + s.number + " " + s.name + ", " + dollars(paid);
      var body = "set: " + s.number + "\npaid: " + paid.toFixed(2) + "\ndate: " + date +
        "\n\nAdded from the Sealed Elves Finder. Close this issue to remove the purchase.";
      var url = "https://github.com/" + repo + "/issues/new?title=" + encodeURIComponent(title) + "&body=" + encodeURIComponent(body);
      window.open(url, "_blank", "noopener");
      msg.className = "form-msg ok";
      msg.innerHTML = "GitHub opened in a new tab with the purchase filled in. Click <b>Create</b> there to save it. The budget and set colors update in about 2 minutes.";
    });

    var list = purchasesData.purchases || [];
    el("pList").innerHTML = list.length === 0
      ? '<p class="empty">No purchases yet.</p>'
      : '<ul class="plist">' + list.slice().sort(function (a, b) { return String(b.date).localeCompare(String(a.date)); }).map(function (p) {
          var s = sets.filter(function (x) { return x.number === p.set; })[0];
          return "<li><span>" + esc(p.date || "") + "</span><b>" + esc(p.set + " " + (s ? s.name : "")) + "</b><span>" + dollars(p.paid) + "</span>" +
            (safeUrl(p.url) ? '<a href="' + esc(safeUrl(p.url)) + '" target="_blank" rel="noopener noreferrer">Remove</a>' : "") + "</li>";
        }).join("") + "</ul>";
  }

  /* If a photo cannot load, show the set number instead of a broken image */
  document.addEventListener("error", function (e) {
    var img = e.target;
    if (img && img.tagName === "IMG" && img.parentNode && img.parentNode.classList.contains("thumb")) {
      var box = img.parentNode;
      var label = document.createElement("span");
      label.className = "ph";
      label.textContent = box.getAttribute("data-num") || "";
      box.replaceChild(label, img);
    }
  }, true);

  /* Start */

  Promise.all([
    loadJson("data/sets.json"), loadJson("data/listings.json"),
    loadJson("data/budget.json"),
    loadJson("data/purchases.json").catch(function () { return { ok: false, purchases: [] }; })
  ])
    .then(function (res) {
      var sets = res[0].sets;
      var data = res[1];
      data.sets = data.sets || {};
      data.images = data.images || {};
      var purchasesData = res[3] || {};
      var purchases = (purchasesData.purchases || []).filter(function (p) { return p && p.set && Number(p.paid) >= 0; });
      var budget = computeBudget(res[2], purchases);
      var owned = ownedMap(purchases);
      showStatus(data);
      showBudget(budget, purchasesData.ok !== false);
      var page = document.body.getAttribute("data-page");
      if (page === "set") renderSet(sets, data, budget, owned);
      else if (page === "add") renderAdd(sets, data, budget, owned, purchasesData);
      else renderHome(sets, data, budget, owned);
    })
    .catch(function (err) {
      el("banner").innerHTML = '<div class="banner bad"><strong>The page could not load its data.</strong>Refresh the page. If this keeps happening, see "Fixing problems" in the setup guide.</div>';
      el("updated").textContent = "";
      if (window.console) console.error(err);
    });
})();
