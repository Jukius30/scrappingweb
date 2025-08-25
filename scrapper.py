import threading, time, random, os, re
import pandas as pd
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinter.scrolledtext import ScrolledText

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager

# =========================
# Helpers
# =========================

def j(a=0.6, b=1.2):
    time.sleep(random.uniform(a, b))

def human_type(el, text, a=0.05, b=0.18):
    for ch in text:
        el.send_keys(ch); j(a, b)

def driver_setup(headless=False):
    o = webdriver.ChromeOptions()
    if headless:
        o.add_argument("--headless=new")
    for arg in [
        "--disable-blink-features=AutomationControlled",
        "--start-maximized",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--lang=en-US,en",
    ]:
        o.add_argument(arg)
    d = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=o)
    d.set_page_load_timeout(45)
    return d

def clean_err(e: Exception) -> str:
    s = str(e)
    return (s.split("Stacktrace:")[0]).strip()[:400]

def first_text(ctx, selectors):
    for by, sel in selectors:
        els = ctx.find_elements(by, sel)
        if els:
            return els[0].text.strip()
    return ""

def pretty_from_slug(url: str, key: str = "/in/") -> str:
    try:
        slug = url.split(key)[1].split("/")[0]
        return " ".join(p.capitalize() for p in slug.replace("-", " ").split())
    except Exception:
        return ""

# Expand "See more" inside a section (Overview/About)
def try_expand_see_more(ctx, d, attempts=3):
    cond = (
        "contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'see more') or "
        "contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'show more') or "
        "contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'read more') or "
        "contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'lihat selengkapnya') or "
        "contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'lihat lebih banyak') or "
        "contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'selengkapnya')"
    )
    for _ in range(attempts):
        try:
            btn = ctx.find_element(By.XPATH, f".//button[{cond}] | .//a[{cond}]")
            d.execute_script("arguments[0].scrollIntoView({behavior:'instant',block:'center'});", btn)
            j(0.2, 0.5)
            try:
                btn.click()
            except Exception:
                d.execute_script("arguments[0].click();", btn)
            j(0.5, 0.9)
        except Exception:
            break  # no more see-more buttons

def cleanup_overview_text(txt: str) -> str:
    if not txt:
        return txt
    txt = re.sub(
        r"\s*(…|\.{3})?\s*(see more|show more|read more|lihat selengkapnya|lihat lebih banyak|selengkapnya)\s*$",
        "",
        txt,
        flags=re.IGNORECASE,
    )
    return txt.strip()

# =========================
# Auth & Search
# =========================

def li_login(d, email, pwd, log):
    d.get("https://www.linkedin.com/login"); j(1, 2)
    human_type(d.find_element(By.ID, "username"), email); j(.2, .6)
    human_type(d.find_element(By.ID, "password"), pwd); j(.2, .6)
    d.find_element(By.XPATH, "//button[@type='submit']").click(); j(2, 3)
    log("✔️ Logged in (or navigated past login page)" if "checkpoint" not in d.current_url
        else "⚠️ Login may need verification")

def open_search(d, kw, mode):
    kwq = kw.strip().replace(" ", "%20")
    vert = "people" if mode == "people" else "companies"
    d.get(f"https://www.linkedin.com/search/results/{vert}/?keywords={kwq}&origin=SWITCH_SEARCH_VERTICAL")
    j(1.5, 2.5)
    try:
        WebDriverWait(d, 10).until(EC.presence_of_element_located(
            (By.XPATH, "//ul[contains(@class,'reusable-search__entity-result-list')]")))
    except Exception:
        pass

def scroll_results(d, passes=2):
    cont = d.find_elements(By.CSS_SELECTOR, "div.scaffold-finite-scroll__content, div.search-results-container")
    tgt = cont[0] if cont else None
    for _ in range(passes):
        if tgt:
            d.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight;", tgt)
        else:
            d.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        j(1.0, 1.6)

# =========================
# Cards / Links
# =========================

def result_cards(d, mode):
    patterns = [
        (By.XPATH, "//ul[contains(@class,'reusable-search__entity-result-list')]/li"),
        (By.CSS_SELECTOR, "li.reusable-search__result-container"),
        (By.CSS_SELECTOR, ".reusable-search__result-container"),
    ]
    if mode == "people":
        patterns += [
            (By.XPATH, "//li[.//a[contains(@href,'/in/')]]"),
            (By.XPATH, "//li[.//button[normalize-space()='Connect' or .//span[normalize-space()='Connect'] "
                        "or normalize-space()='Hubungkan' or .//span[normalize-space()='Hubungkan']]]"),
        ]
    else:  # companies
        patterns += [
            (By.XPATH, "//li[.//a[contains(@href,'/company/') or contains(@href,'/school/')]]"),
            (By.XPATH, "//li[.//button[normalize-space()='Follow' or .//span[normalize-space()='Follow'] "
                        "or normalize-space()='Ikuti' or .//span[normalize-space()='Ikuti']]]"),
            (By.XPATH, "//div[contains(@class,'entity-result__content')]/ancestor::li"),
        ]

    for by, sel in patterns:
        try:
            WebDriverWait(d, 10).until(EC.presence_of_element_located((by, sel)))
            got = d.find_elements(by, sel)
            if got:
                return got
        except Exception:
            continue

    return d.find_elements(
        By.XPATH,
        "//li[contains(@class,'reusable-search__result-container') or contains(@class,'entity-result__item') "
        "or .//a[contains(@href,'/company/') or contains(@href,'/school/')]]"
    )

def name_hint_from_card(card):
    try:
        a = card.find_element(By.XPATH, ".//a[contains(@href,'/in/')]")
        spans = a.find_elements(By.XPATH, ".//span[@aria-hidden='true']")
        for s in spans:
            t = s.text.strip()
            if t and len(t) > 1:
                return t
    except Exception:
        pass
    try:
        return (card.text or "").splitlines()[0].strip()
    except Exception:
        return ""

def company_hint_from_card(card):
    try:
        a = card.find_element(By.XPATH, ".//a[contains(@href,'/company/') or contains(@href,'/school/')]")
        span = first_text(a, [(By.XPATH, ".//span[@aria-hidden='true']")])
        return span or (card.text or "").splitlines()[0].strip()
    except Exception:
        return (card.text or "").splitlines()[0].strip()

def link_from_card(card, mode):
    href = ""
    try:
        if mode == "people":
            a = card.find_element(By.XPATH, ".//a[contains(@href,'/in/')]")
        else:
            a = card.find_element(By.XPATH, ".//a[contains(@href,'/company/') or contains(@href,'/school/')]")
        href = a.get_attribute("href") or ""
    except NoSuchElementException:
        pass

    if href:
        href = href.split("?", 1)[0].split("#", 1)[0]
        if mode == "companies" and href.endswith("/about"):
            href = href[:-6]
        return href
    return None

def next_button(d):
    xp = (
        "//button[contains(@aria-label,'Next') and not(@disabled)] | "
        "//span[normalize-space()='Next']/ancestor::button[not(@disabled)] | "
        "//button[.//span[contains(normalize-space(.),'Next')] and not(@disabled)] | "
        "//button[@aria-label='Berikutnya' and not(@disabled)] | "
        "//span[normalize-space()='Berikutnya']/ancestor::button[not(@disabled)]"
    )
    try:
        return d.find_element(By.XPATH, xp)
    except NoSuchElementException:
        return None

# =========================
# Profile parsers
# =========================

def profile_basic_person(d):
    try:
        WebDriverWait(d, 8).until(EC.presence_of_element_located((By.XPATH,
            "//h1[contains(@class,'text-heading') or contains(@class,'break-words')] | "
            "//div[contains(@class,'pv-text-details__left-panel')]//h1")))
    except Exception:
        pass
    return {
        "name": first_text(d, [(By.CSS_SELECTOR, "h1.text-heading-xlarge"),
                               (By.CSS_SELECTOR, "div.ph5.pb5 h1")]),
        "headline": first_text(d, [(By.CSS_SELECTOR, "div.text-body-medium.break-words"),
                                   (By.CSS_SELECTOR, "div.ph5.pb5 div.text-body-medium")]),
        "location": first_text(d, [(By.XPATH, "//span[contains(@class,'text-body-small') and contains(@class,'inline')]")]),
        "about": first_text(d, [(By.XPATH, "//section[contains(@id,'about') or .//h2[contains(.,'About')]]")]),
    }

def profile_exps(d, url):
    d.get(url.rstrip('/') + "/details/experience/"); j(1.2, 1.8)
    exps = []
    items = d.find_elements(By.XPATH, "//li[@data-view-name='profile-component-entity' or @data-view-name='experience-item' or @role='listitem']")
    items = items or d.find_elements(By.CSS_SELECTOR, "li")
    for li in items:
        try:
            title = first_text(li, [(By.CSS_SELECTOR, ".t-bold span[aria-hidden='true']"),
                                    (By.CSS_SELECTOR, "span[aria-hidden='true']")])
            company = first_text(li, [(By.XPATH, ".//span[contains(@class,'t-14') and contains(@class,'t-normal')]")])
            try:
                date_range = li.find_element(By.XPATH, ".//span[contains(@class,'t-14') and (contains(.,'Present') or contains(.,'–'))]").text.strip()
            except NoSuchElementException:
                date_range = ""
            smalls = li.find_elements(By.CSS_SELECTOR, "span.t-14.t-normal.t-black--light")
            location = (smalls[-1].text.strip() if len(smalls) >= 2 else "")
            try:
                desc = li.find_element(By.XPATH, ".//div[contains(@class,'inline-show-more-text')]").text.strip()
            except NoSuchElementException:
                desc = ""
            if any([title, company, date_range, location, desc]):
                exps.append({"title": title, "company": company, "date_range": date_range,
                             "location": location, "description": desc})
        except Exception:
            continue
    return exps

def profile_basic_company(d):
    # Top card
    name = first_text(d, [
        (By.CSS_SELECTOR, "h1.org-top-card-summary__title"),
        (By.CSS_SELECTOR, "h1")
    ])
    tagline = first_text(d, [
        (By.CSS_SELECTOR, "p.org-top-card-summary__tagline"),
        (By.CSS_SELECTOR, "div.text-body-medium")
    ])

    # Find Overview section first, fallback to About
    sec = None
    for by, sel in [
        (By.XPATH, "//section[.//h2[contains(translate(.,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'overview')]]"),
        (By.XPATH, "//div[contains(@class,'org-grid__content')][.//h2[contains(translate(.,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'overview')]]"),
        (By.XPATH, "//section[contains(@class,'about') or contains(@data-test-id,'about')]"),
    ]:
        els = d.find_elements(by, sel)
        if els:
            sec = els[0]
            break

    overview = ""
    if sec:
        try_expand_see_more(sec, d, attempts=3)
        parts = []
        for by, sel in [
            (By.XPATH, ".//p[normalize-space()]"),
            (By.XPATH, ".//div[contains(@class,'break-words')][normalize-space()]"),
            (By.XPATH, ".//span[contains(@class,'break-words')][normalize-space()]"),
        ]:
            for el in sec.find_elements(by, sel):
                t = el.text.strip()
                if t and t not in parts:
                    parts.append(t)
        overview = "\n".join(parts).strip() if parts else sec.text.strip()

    overview = cleanup_overview_text(overview)

    # Website
    website = ""
    try:
        link = d.find_element(
            By.XPATH,
            "//a[contains(@href,'http') and (contains(.,'Website') or contains(.,'Situs'))]"
        )
        website = link.get_attribute('href') or link.text.strip()
    except Exception:
        try:
            link = d.find_element(
                By.XPATH,
                "//section[contains(@class,'about') or contains(@data-test-id,'about')]//a[starts-with(@href,'http')]"
            )
            website = link.get_attribute('href')
        except Exception:
            website = ""

    return {
        "company_name": name,
        "tagline": tagline,
        "website": website,
        "overview": overview,
    }

# =========================
# Scrape loop
# =========================

def scrape(d, keyword, max_pages, log, stop, autosave=None, mode="people"):
    open_search(d, keyword, mode)
    results, page = [], 1
    while not stop[0]:
        log(f"🔎 Page {page}: scanning results…")
        scroll_results(d, 2)
        cards = result_cards(d, mode)
        if not cards:
            log("⚠️ No cards found; rescrolling and retrying…")
            scroll_results(d, 3); cards = result_cards(d, mode)
        log(f"• Found {len(cards)} result cards on this page")

        results_url = d.current_url
        items = []
        for c in cards:
            link = link_from_card(c, mode)
            if not link: continue
            if mode == "people" and "/in/" not in link: continue
            if mode == "companies" and ("/company/" not in link and "/school/" not in link): continue
            hint = (name_hint_from_card(c) if mode == "people" else company_hint_from_card(c))
            items.append((link, hint))

        for i, (link, hint) in enumerate(items, 1):
            if stop[0]: break
            try:
                d.get(link); j(1.1, 1.7)
                if mode == "people":
                    prof = profile_basic_person(d)
                    if not prof.get("name"):
                        title_name = (d.title or "").split(" | ")[0].strip()
                        prof["name"] = title_name or hint or pretty_from_slug(link, "/in/") or "Unknown"
                    prof["profile_url"] = link
                    prof["experiences"] = profile_exps(d, link)
                else:
                    comp = profile_basic_company(d)
                    if not comp.get("company_name"):
                        comp["company_name"] = hint or pretty_from_slug(link, "/company/") or pretty_from_slug(link, "/school/")
                    comp["company_url"] = link
                    prof = comp

                results.append(prof)
                try:
                    if autosave and len(results) % 3 == 0:
                        autosave(results)  # write to SAME output file
                except Exception as _e:
                    log(f"⚠️ Autosave failed: {_e}")

                label = prof.get('name') if mode == 'people' else prof.get('company_name')
                log(f"  ✔️ [{i}/{len(items)}] {label or 'Unknown'} — {link}")
            except Exception as e:
                log(f"  ⚠️ Error: {clean_err(e)}")
                try:
                    if autosave:
                        autosave(results)
                except Exception as _e:
                    log(f"⚠️ Autosave failed: {_e}")
            finally:
                try:
                    d.get(results_url); j(.8, 1.2)
                except Exception:
                    pass

        if max_pages and page >= max_pages:
            log("⏹️ Reached max pages limit."); break
        nxt = next_button(d)
        if not nxt:
            log("✅ No more pages (Next button not found/disabled). Done.")
            try:
                if autosave:
                    autosave(results)
            except Exception as _e:
                log(f"⚠️ Autosave failed: {_e}")
            break
        d.execute_script("arguments[0].scrollIntoView({behavior:'smooth',block:'center'});", nxt)
        j(.6, 1.0); nxt.click(); j(1.2, 1.8); page += 1
    return results

# =========================
# Formatting / Save
# =========================

def fmt_exps(exps):
    out = []
    for e in exps or []:
        t = (e.get('title') or '').strip()
        c = (e.get('company') or '').strip()
        dr = (e.get('date_range') or '').strip()
        loc = (e.get('location') or '').strip()
        desc = (e.get('description') or '').strip()
        head = " ".join([x for x in [t, f"at {c}" if c else ""] if x]).strip()
        if dr: head += f" ({dr})"
        if loc: head += f" — {loc}"
        if desc: head += f": {desc}"
        if head: out.append("- " + head)
    return "\n".join(out)

def to_df_people(results):
    rows = [{
        "Name": r.get("name",""),
        "Headline": r.get("headline",""),
        "Location": r.get("location",""),
        "About": r.get("about",""),
        "Profile URL": r.get("profile_url",""),
        "Experiences": fmt_exps(r.get("experiences",[])),
    } for r in results]
    return pd.DataFrame(rows, columns=["Name","Headline","Location","About","Profile URL","Experiences"])

def to_df_companies(results):
    rows = [{
        "Company Name": r.get("company_name",""),
        "Tagline": r.get("tagline",""),
        "Website": r.get("website",""),
        "Overview": r.get("overview","") or r.get("about",""),
        "Company URL": r.get("company_url",""),
    } for r in results]
    return pd.DataFrame(rows, columns=["Company Name","Tagline","Website","Overview","Company URL"])

def save_partial(results, out_path, fmt, log, mode):
    """Write partial/final results to the SAME output file."""
    if not results:
        return
    df = to_df_people(results) if mode == 'people' else to_df_companies(results)
    try:
        if fmt == 'csv':
            df.to_csv(out_path, index=False)
        else:
            df.to_excel(out_path, index=False)
        log(f"💾 Saved {len(df)} rows to {out_path}")
    except Exception as e:
        log(f"⚠️ Save failed: {e}")

# =========================
# UI (Tkinter)
# =========================

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("LinkedIn Scraper (People / Companies)")
        self.geometry("860x640")
        self.driver = None
        self.worker = None
        self.stop = [False]
        self.build()

    def build(self):
        g = ttk.Frame(self); g.pack(fill=tk.X, padx=10, pady=10)

        def add(label, var, row, width=40, pw=False):
            ttk.Label(g, text=label).grid(row=row, column=0, sticky=tk.W)
            e = ttk.Entry(g, textvariable=var, width=width)
            if pw: e.config(show='*')
            e.grid(row=row, column=1, sticky=tk.W)

        self.email = tk.StringVar(); add("LinkedIn Email", self.email, 0)
        self.pwd = tk.StringVar(); add("Password", self.pwd, 1, pw=True)
        self.kw = tk.StringVar(value="Software Engineer Indonesia"); add("Keyword", self.kw, 2)
        self.pages = tk.StringVar(value="3")
        ttk.Label(g, text="Max Pages").grid(row=3, column=0, sticky=tk.W)
        ttk.Entry(g, textvariable=self.pages, width=10).grid(row=3, column=1, sticky=tk.W)
        self.headless = tk.BooleanVar(value=False)
        ttk.Checkbutton(g, text="Headless (hide browser)", variable=self.headless).grid(row=4, column=1, sticky=tk.W)

        # Type switch
        t = ttk.Frame(self); t.pack(fill=tk.X, padx=10, pady=6)
        ttk.Label(t, text="Type:").grid(row=0, column=0, sticky=tk.W)
        self.mode = tk.StringVar(value="people")
        ttk.Radiobutton(t, text="People", value="people", variable=self.mode, command=self.on_mode_change).grid(row=0, column=1, sticky=tk.W)
        ttk.Radiobutton(t, text="Companies", value="companies", variable=self.mode, command=self.on_mode_change).grid(row=0, column=2, sticky=tk.W)

        s = ttk.Frame(self); s.pack(fill=tk.X, padx=10, pady=6)
        ttk.Label(s, text="Save as:").grid(row=0, column=0, sticky=tk.W)
        self.fmt = tk.StringVar(value="csv")
        ttk.Radiobutton(s, text="CSV", value="csv", variable=self.fmt).grid(row=0, column=1, sticky=tk.W)
        ttk.Radiobutton(s, text="Excel", value="xlsx", variable=self.fmt).grid(row=0, column=2, sticky=tk.W)
        ttk.Label(s, text="Output file:").grid(row=1, column=0, sticky=tk.W)
        self.out = tk.StringVar(value="people_results.csv")
        ttk.Entry(s, textvariable=self.out, width=56).grid(row=1, column=1, sticky=tk.W)
        ttk.Button(s, text="Browse…", command=self.browse).grid(row=1, column=2, padx=5)

        b = ttk.Frame(self); b.pack(fill=tk.X, padx=10, pady=6)
        ttk.Button(b, text="Start", command=self.start).pack(side=tk.LEFT)
        ttk.Button(b, text="Stop", command=self.stop_req).pack(side=tk.LEFT, padx=8)

        self.log = ScrolledText(self, height=20)
        self.log.pack(fill=tk.BOTH, expand=True, padx=10, pady=8)
        self.log.configure(state=tk.DISABLED)
        for w in g.winfo_children(): w.grid_configure(padx=5, pady=5)

    def on_mode_change(self):
        cur = (self.out.get() or "").strip().lower()
        defaults = {"people": "people_results.csv", "companies": "companies_results.csv"}
        if (not cur) or cur.endswith(("linkedin_results.csv", "people_results.csv", "companies_results.csv")):
            self.out.set(defaults.get(self.mode.get(), "results.csv"))

    def browse(self):
        ft = [("CSV files", "*.csv")] if self.fmt.get() == "csv" else [("Excel files", "*.xlsx")]
        path = filedialog.asksaveasfilename(
            defaultextension=(".csv" if self.fmt.get() == "csv" else ".xlsx"),
            filetypes=ft
        )
        if path:
            self.out.set(path)

    def log_add(self, msg):
        self.log.configure(state=tk.NORMAL)
        self.log.insert(tk.END, str(msg) + "\n")
        self.log.see(tk.END)
        self.log.configure(state=tk.DISABLED)
        self.update_idletasks()

    def start(self):
        if self.worker and self.worker.is_alive():
            return messagebox.showinfo("Info", "Scraping already running…")
        if not all([self.email.get().strip(), self.pwd.get().strip(), self.kw.get().strip()]):
            return messagebox.showerror("Missing", "Please fill Email, Password, and Keyword")
        try:
            pages = int(self.pages.get().strip() or 1)
        except ValueError:
            pages = 1

        mode = self.mode.get()
        default_name = "people_results.csv" if mode == 'people' else "companies_results.csv"
        fmt, out = self.fmt.get(), self.out.get().strip() or default_name
        if fmt == "csv" and not out.lower().endswith(".csv"): out += ".csv"
        if fmt == "xlsx" and not out.lower().endswith(".xlsx"): out += ".xlsx"
        self.stop[0] = False

        def work(email, pwd, kw, pages, fmt, headless, out, mode):
            d = None; res = []
            try:
                self.log_add("Launching Chrome…")
                d = driver_setup(headless=headless); self.driver = d
                self.log_add("Logging in to LinkedIn…")
                li_login(d, email, pwd, self.log_add)

                def autosave_cb(r):
                    try:
                        save_partial(r, out, fmt, self.log_add, mode)  # same file
                    except Exception as _e:
                        self.log_add(f"⚠️ Autosave failed: {_e}")

                self.log_add(f"Searching {mode} for: '{kw}'")
                res = scrape(d, kw, pages, self.log_add, self.stop, autosave=autosave_cb, mode=mode)
                self.log_add(f"Collected {len(res)} records.")
                df = to_df_people(res) if mode == 'people' else to_df_companies(res)
                (df.to_csv(out, index=False) if fmt == "csv" else df.to_excel(out, index=False))
                self.log_add(f"✅ Saved results to {out}")
            except Exception as e:
                self.log_add("❌ Error: " + clean_err(e))
                try:
                    save_partial(res, out, fmt, self.log_add, mode)  # write whatever we have to the same file
                except Exception as _e:
                    self.log_add(f"⚠️ Autosave failed: {_e}")
            finally:
                try:
                    d.quit()
                except Exception:
                    pass
                self.driver = None
                self.log_add("Browser closed.")

        self.worker = threading.Thread(
            target=work,
            args=(self.email.get().strip(), self.pwd.get().strip(), self.kw.get().strip(),
                  pages, fmt, self.headless.get(), out, mode),
            daemon=True
        )
        self.worker.start()

    def stop_req(self):
        self.stop[0] = True
        self.log_add("⏹️ Stop requested. Finishing current step…")

if __name__ == "__main__":
    App().mainloop()
