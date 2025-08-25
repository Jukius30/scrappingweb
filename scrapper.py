import threading, time, random, traceback, os
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

# -----------------------------
# Helpers
# -----------------------------

def j(a=0.6, b=1.2):
    time.sleep(random.uniform(a, b))


def human_type(el, text, a=0.05, b=0.18):
    for ch in text:
        el.send_keys(ch)
        j(a, b)


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

# -----------------------------
# Scraping
# -----------------------------

def li_login(d, email, pwd, log):
    d.get("https://www.linkedin.com/login"); j(1, 2)
    human_type(d.find_element(By.ID, "username"), email); j(.2, .6)
    human_type(d.find_element(By.ID, "password"), pwd); j(.2, .6)
    d.find_element(By.XPATH, "//button[@type='submit']").click(); j(2, 3)
    log(
        "✔️ Logged in (or navigated past login page)"
        if "checkpoint" not in d.current_url
        else "⚠️ Login may need verification"
    )


def open_search(d, kw):
    d.get(
        f"https://www.linkedin.com/search/results/people/?keywords={kw.strip().replace(' ', '%20')}&origin=SWITCH_SEARCH_VERTICAL"
    )
    j(1.5, 2.5)
    try:
        WebDriverWait(d, 10).until(
            EC.presence_of_element_located(
                (By.XPATH, "//ul[contains(@class,'reusable-search__entity-result-list')]")
            )
        )
    except Exception:
        pass


def scroll_results(d, passes=2):
    cont = d.find_elements(
        By.CSS_SELECTOR,
        "div.scaffold-finite-scroll__content, div.search-results-container",
    )
    tgt = cont[0] if cont else None
    for _ in range(passes):
        if tgt:
            d.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight;", tgt)
        else:
            d.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        j(1.0, 1.6)


def result_cards(d):
    patterns = [
        (By.XPATH, "//ul[contains(@class,'reusable-search__entity-result-list')]/li"),
        (By.CSS_SELECTOR, "li.reusable-search__result-container"),
        (By.CSS_SELECTOR, ".reusable-search__result-container"),
        (
            By.XPATH,
            "//button[normalize-space()='Connect' or .//span[normalize-space()='Connect']]/ancestor::li",
        ),
    ]
    for by, sel in patterns:
        try:
            WebDriverWait(d, 7).until(EC.presence_of_element_located((by, sel)))
            got = d.find_elements(by, sel)
            if got:
                return got
        except Exception:
            continue
    return d.find_elements(By.XPATH, "//li[contains(@class,'entity-result__item')]")


def first_text(ctx, selectors):
    for by, sel in selectors:
        els = ctx.find_elements(by, sel)
        if els:
            return els[0].text.strip()
    return ""


def profile_basic(d):
    return {
        "name": first_text(
            d,
            [
                (By.CSS_SELECTOR, "h1.text-heading-xlarge"),
                (By.CSS_SELECTOR, "div.ph5.pb5 h1"),
            ],
        ),
        "headline": first_text(
            d,
            [
                (By.CSS_SELECTOR, "div.text-body-medium.break-words"),
                (By.CSS_SELECTOR, "div.ph5.pb5 div.text-body-medium"),
            ],
        ),
        "location": first_text(
            d,
            [
                (
                    By.XPATH,
                    "//span[contains(@class,'text-body-small') and contains(@class,'inline')]",
                ),
            ],
        ),
        "about": first_text(
            d,
            [
                (
                    By.XPATH,
                    "//section[contains(@id,'about') or .//h2[contains(.,'About')]]",
                ),
            ],
        ),
    }


def profile_exps(d, url):
    d.get(url.rstrip("/") + "/details/experience/"); j(1.2, 1.8)
    exps = []
    items = d.find_elements(
        By.XPATH,
        "//li[@data-view-name='profile-component-entity' or @data-view-name='experience-item' or @role='listitem']",
    )
    items = items or d.find_elements(By.CSS_SELECTOR, "li")
    for li in items:
        try:
            title = first_text(
                li,
                [
                    (By.CSS_SELECTOR, ".t-bold span[aria-hidden='true']"),
                    (By.CSS_SELECTOR, "span[aria-hidden='true']"),
                ],
            )
            company = first_text(
                li,
                [
                    (
                        By.XPATH,
                        ".//span[contains(@class,'t-14') and contains(@class,'t-normal')]",
                    )
                ],
            )
            try:
                date_range = (
                    li.find_element(
                        By.XPATH,
                        ".//span[contains(@class,'t-14') and (contains(.,'Present') or contains(.,'–'))]",
                    )
                    .text.strip()
                )
            except NoSuchElementException:
                date_range = ""
            smalls = li.find_elements(
                By.CSS_SELECTOR, "span.t-14.t-normal.t-black--light"
            )
            location = smalls[-1].text.strip() if len(smalls) >= 2 else ""
            try:
                desc = (
                    li.find_element(
                        By.XPATH, ".//div[contains(@class,'inline-show-more-text')]"
                    )
                    .text.strip()
                )
            except NoSuchElementException:
                desc = ""
            if any([title, company, date_range, location, desc]):
                exps.append(
                    {
                        "title": title,
                        "company": company,
                        "date_range": date_range,
                        "location": location,
                        "description": desc,
                    }
                )
        except Exception:
            continue
    return exps


def link_from_card(card):
    try:
        href = card.find_element(By.XPATH, ".//a[contains(@href,'/in/')]").get_attribute(
            "href"
        )
        return href.split("?")[0] if href else None
    except NoSuchElementException:
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


def scrape(d, keyword, max_pages, log, stop, autosave=None):
    open_search(d, keyword)
    results, page = [], 1
    while not stop[0]:
        log(f"🔎 Page {page}: scanning results…")
        scroll_results(d, 2)
        cards = result_cards(d)
        if not cards:
            log("⚠️ No cards found; rescrolling and retrying…")
            scroll_results(d, 3)
            cards = result_cards(d)
        log(f"• Found {len(cards)} result cards on this page")

        results_url = d.current_url
        links = [l for l in (link_from_card(c) for c in cards) if l and "/in/" in l]
        for i, link in enumerate(links, 1):
            if stop[0]:
                break
            try:
                d.get(link); j(1.1, 1.7)
                prof = profile_basic(d)
                prof["profile_url"] = link
                prof["experiences"] = profile_exps(d, link)
                results.append(prof)

                # AUTOSAVE setiap 3 profil
                try:
                    if autosave and len(results) % 3 == 0:
                        autosave(results)
                except Exception as _e:
                    log(f"⚠️ Autosave failed: {_e}")

                log(
                    f"  ✔️ [{i}/{len(links)}] {prof.get('name') or 'Unknown'} — {link}"
                )
            except Exception as e:
                log(f"  ⚠️ Error: {e}")
                # AUTOSAVE saat error (mis. koneksi/driver)
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
            log("⏹️ Reached max pages limit.")
            break

        nxt = next_button(d)
        if not nxt:
            log("✅ No more pages (Next button not found/disabled). Done.")
            # autosave final snapshot juga boleh
            try:
                if autosave:
                    autosave(results)
            except Exception as _e:
                log(f"⚠️ Autosave failed: {_e}")
            break

        d.execute_script(
            "arguments[0].scrollIntoView({behavior:'smooth',block:'center'});", nxt
        )
        j(.6, 1.0); nxt.click(); j(1.2, 1.8); page += 1
    return results


def fmt_exps(exps):
    out = []
    for e in exps or []:
        t = (e.get("title") or "").strip(); c = (e.get("company") or "").strip()
        dr = (e.get("date_range") or "").strip(); loc = (e.get("location") or "").strip(); desc = (e.get("description") or "").strip()
        head = " ".join([x for x in [t, f"at {c}" if c else ""] if x]).strip()
        if dr:
            head += f" ({dr})"
        if loc:
            head += f" — {loc}"
        if desc:
            head += f": {desc}"
        if head:
            out.append("- " + head)
    return "\n".join(out)


def to_df(results):
    rows = [
        {
            "Name": r.get("name", ""),
            "Headline": r.get("headline", ""),
            "Location": r.get("location", ""),
            "About": r.get("about", ""),
            "Profile URL": r.get("profile_url", ""),
            "Experiences": fmt_exps(r.get("experiences", [])),
        }
        for r in results
    ]
    return pd.DataFrame(
        rows,
        columns=["Name", "Headline", "Location", "About", "Profile URL", "Experiences"],
    )


def save_partial(results, out_path, fmt, log, tag="autosave"):
    if not results:
        return
    base, ext = os.path.splitext(out_path)
    if not ext:
        ext = ".csv" if fmt == "csv" else ".xlsx"
    path = f"{base}.{tag}{ext}"
    df = to_df(results)
    try:
        if fmt == "csv":
            df.to_csv(path, index=False)
        else:
            df.to_excel(path, index=False)
        log(f"🧷 Autosaved partial results to {path} ({len(df)} rows)")
    except Exception as e:
        log(f"⚠️ Autosave failed to write: {e}")

# -----------------------------
# UI (Tkinter)
# -----------------------------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("LinkedIn People Scraper (Tkinter)"); self.geometry("820x600")
        self.driver = None; self.worker = None; self.stop = [False]
        self.build()

    def build(self):
        g = ttk.Frame(self); g.pack(fill=tk.X, padx=10, pady=10)

        def add(label, var, row, width=40, pw=False):
            ttk.Label(g, text=label).grid(row=row, column=0, sticky=tk.W)
            e = ttk.Entry(g, textvariable=var, width=width)
            if pw:
                e.config(show='*')
            e.grid(row=row, column=1, sticky=tk.W)

        self.email = tk.StringVar(); add("LinkedIn Email", self.email, 0)
        self.pwd = tk.StringVar(); add("Password", self.pwd, 1, pw=True)
        self.kw = tk.StringVar(); add("Keyword", self.kw, 2)
        self.pages = tk.StringVar(); ttk.Label(g, text="Max Pages (100 Max)").grid(row=3, column=0, sticky=tk.W); ttk.Entry(g, textvariable=self.pages, width=10).grid(row=3, column=1, sticky=tk.W)
        self.headless = tk.BooleanVar(value=False); ttk.Checkbutton(g, text="Headless (hide browser)", variable=self.headless).grid(row=4, column=1, sticky=tk.W)

        s = ttk.Frame(self); s.pack(fill=tk.X, padx=10, pady=6)
        ttk.Label(s, text="Save as:").grid(row=0, column=0, sticky=tk.W)
        self.fmt = tk.StringVar(value="csv")
        ttk.Radiobutton(s, text="CSV", value="csv", variable=self.fmt).grid(row=0, column=1, sticky=tk.W)
        ttk.Radiobutton(s, text="Excel", value="xlsx", variable=self.fmt).grid(row=0, column=2, sticky=tk.W)
        ttk.Label(s, text="Output file:").grid(row=1, column=0, sticky=tk.W)
        self.out = tk.StringVar()
        ttk.Entry(s, textvariable=self.out, width=50).grid(row=1, column=1, sticky=tk.W)
        ttk.Button(s, text="Browse…", command=self.browse).grid(row=1, column=2, padx=5)

        b = ttk.Frame(self); b.pack(fill=tk.X, padx=10, pady=6)
        ttk.Button(b, text="Start", command=self.start).pack(side=tk.LEFT)
        ttk.Button(b, text="Stop", command=self.stop_req).pack(side=tk.LEFT, padx=8)

        self.log = ScrolledText(self, height=20); self.log.pack(fill=tk.BOTH, expand=True, padx=10, pady=8); self.log.configure(state=tk.DISABLED)
        for w in g.winfo_children(): w.grid_configure(padx=5, pady=5)
        for w in s.winfo_children(): w.grid_configure(padx=5, pady=5)

    def browse(self):
        ft = [("CSV files", "*.csv")] if self.fmt.get() == "csv" else [("Excel files", "*.xlsx")]
        path = filedialog.asksaveasfilename(
            defaultextension=(".csv" if self.fmt.get() == "csv" else ".xlsx"),
            filetypes=ft,
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
        fmt, out = self.fmt.get(), self.out.get().strip() or (
            "linkedin_results.csv" if self.fmt.get() == "csv" else "linkedin_results.xlsx"
        )
        if fmt == "csv" and not out.lower().endswith('.csv'):
            out += '.csv'
        if fmt == "xlsx" and not out.lower().endswith('.xlsx'):
            out += '.xlsx'
        self.stop[0] = False

        def work(email, pwd, kw, pages, fmt, headless, out):
            d = None
            res = []
            try:
                self.log_add("Launching Chrome…"); d = driver_setup(headless=headless); self.driver = d
                self.log_add("Logging in to LinkedIn…"); li_login(d, email, pwd, self.log_add)

                def autosave_cb(r):
                    try:
                        save_partial(r, out, fmt, self.log_add)
                    except Exception as _e:
                        self.log_add(f"⚠️ Autosave failed: {_e}")

                self.log_add(f"Searching people for: '{kw}'")
                res = scrape(d, kw, pages, self.log_add, self.stop, autosave=autosave_cb)
                self.log_add(f"Collected {len(res)} profiles.")
                df = to_df(res)
                (df.to_csv(out, index=False) if fmt == "csv" else df.to_excel(out, index=False))
                self.log_add(f"✅ Saved results to {out}")
            except Exception as e:
                self.log_add("❌ Error: " + str(e))
                try:
                    save_partial(res, out, fmt, self.log_add)
                except Exception as _e:
                    self.log_add(f"⚠️ Autosave failed: {_e}")
                self.log_add(traceback.format_exc())
            finally:
                try:
                    d.quit()
                except Exception:
                    pass
                self.driver = None; self.log_add("Browser closed.")

        self.worker = threading.Thread(
            target=work,
            args=(
                self.email.get().strip(),
                self.pwd.get().strip(),
                self.kw.get().strip(),
                pages,
                fmt,
                self.headless.get(),
                out,
            ),
            daemon=True,
        )
        self.worker.start()

    def stop_req(self):
        self.stop[0] = True; self.log_add("⏹️ Stop requested. Finishing current step…")

if __name__ == "__main__":
    App().mainloop()