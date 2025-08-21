import threading
import time
import random
import json
import traceback
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
# Utility helpers
# -----------------------------

def sleep_jitter(a=0.6, b=1.2):
    time.sleep(random.uniform(a, b))


def type_like_human(el, text: str, min_delay=0.05, max_delay=0.18):
    for ch in text:
        el.send_keys(ch)
        time.sleep(random.uniform(min_delay, max_delay))


def setup_driver(headless=False):
    opts = webdriver.ChromeOptions()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--start-maximized")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--lang=en-US,en")
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=opts)
    driver.set_page_load_timeout(45)
    return driver


# -----------------------------
# LinkedIn scraping routines
# -----------------------------

def linkedin_login(driver, email, password, log):
    driver.get("https://www.linkedin.com/login")
    sleep_jitter(1.0, 2.0)

    user_el = driver.find_element(By.ID, "username")
    pass_el = driver.find_element(By.ID, "password")
    type_like_human(user_el, email)
    sleep_jitter(0.2, 0.6)
    type_like_human(pass_el, password)
    sleep_jitter(0.2, 0.6)
    driver.find_element(By.XPATH, "//button[@type='submit']").click()
    sleep_jitter(2.0, 3.0)

    if "feed" in driver.current_url or "checkpoint" not in driver.current_url:
        log("✔️ Logged in (or navigated past login page)")
    else:
        log("⚠️ Login may have failed or needs verification (checkpoint)")


def open_people_search(driver, keyword):
    q = keyword.strip().replace(" ", "%20")
    url = f"https://www.linkedin.com/search/results/people/?keywords={q}&origin=SWITCH_SEARCH_VERTICAL"
    driver.get(url)
    sleep_jitter(1.5, 2.5)
    # Wait for list container to render
    try:
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.XPATH, "//ul[contains(@class,'reusable-search__entity-result-list')]")))
    except Exception:
        pass


def scroll_results_page(driver, passes=2):
    # Try scrolling the finite-scroll container; fallback to window
    containers = driver.find_elements(By.CSS_SELECTOR, "div.scaffold-finite-scroll__content, div.search-results-container")
    target = containers[0] if containers else None
    for _ in range(passes):
        if target:
            driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight;", target)
        else:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        sleep_jitter(1.0, 1.6)


def extract_result_cards(driver):
    # Wait for any recognizable search result pattern to appear
    patterns = [
        (By.XPATH, "//ul[contains(@class,'reusable-search__entity-result-list')]/li"),
        (By.CSS_SELECTOR, "li.reusable-search__result-container"),
        (By.CSS_SELECTOR, ".reusable-search__result-container"),
        # Fallback: rows that have a Connect button
        (By.XPATH, "//button[normalize-space()='Connect' or .//span[normalize-space()='Connect']]/ancestor::li"),
    ]

    cards = []
    for by, sel in patterns:
        try:
            WebDriverWait(driver, 10).until(EC.presence_of_element_located((by, sel)))
            found = driver.find_elements(by, sel)
            if found:
                cards = found
                break
        except Exception:
            continue

    # As a last resort, grab any entity-result container
    if not cards:
        cards = driver.find_elements(By.XPATH, "//div[contains(@class,'entity-result')]/ancestor::li | //li[contains(@class,'entity-result__item')]")
    return cards
    # Last resort XPaths
    cards = driver.find_elements(By.XPATH, "//li[contains(@class,'reusable-search__result-container') or contains(@class,'entity-result__item')]")
    return cards


def safe_get_text(el):
    try:
        return el.text.strip()
    except Exception:
        return ""


def get_profile_link_from_card(card):
    # Robustly grab any link pointing to /in/
    # 1) direct /in/ links within the card
    try:
        a = card.find_element(By.XPATH, ".//a[contains(@href,'/in/')]")
        href = a.get_attribute("href")
        if href:
            return href.split("?")[0]
    except NoSuchElementException:
        pass
    # 2) app-aware-link fallback
    try:
        a = card.find_element(By.CSS_SELECTOR, "a.app-aware-link")
        href = a.get_attribute("href")
        if href and "/in/" in href:
            return href.split("?")[0]
    except NoSuchElementException:
        pass
    return None
    return None


def extract_profile_basic(driver):
    data = {
        "name": "",
        "headline": "",
        "location": "",
        "about": "",
        "current_company": "",
    }

    for sel in ["h1.text-heading-xlarge", "div.ph5.pb5 h1"]:
        els = driver.find_elements(By.CSS_SELECTOR, sel)
        if els:
            data["name"] = safe_get_text(els[0])
            break

    for sel in ["div.text-body-medium.break-words", "div.ph5.pb5 div.text-body-medium"]:
        els = driver.find_elements(By.CSS_SELECTOR, sel)
        if els:
            data["headline"] = safe_get_text(els[0])
            break

    try:
        loc_el = driver.find_element(By.XPATH, "//span[contains(@class,'text-body-small') and contains(@class,'inline')]")
        data["location"] = safe_get_text(loc_el)
    except NoSuchElementException:
        pass

    try:
        about_el = driver.find_element(By.XPATH, "//section[contains(@id,'about') or .//h2[contains(.,'About')]]")
        data["about"] = safe_get_text(about_el)
    except NoSuchElementException:
        pass

    return data


def extract_experiences(driver, profile_url):
    url = profile_url.rstrip('/') + "/details/experience/"
    driver.get(url)
    sleep_jitter(1.2, 1.8)

    exps = []
    items = driver.find_elements(By.XPATH, "//li[@data-view-name='profile-component-entity' or @data-view-name='experience-item' or @role='listitem']")
    if not items:
        items = driver.find_elements(By.CSS_SELECTOR, "li")

    for li in items:
        try:
            title = ""
            company = ""
            date_range = ""
            location = ""
            desc = ""

            for sel in [".t-bold span[aria-hidden='true']", "span[aria-hidden='true']"]:
                els = li.find_elements(By.CSS_SELECTOR, sel)
                if els:
                    title = safe_get_text(els[0])
                    break

            try:
                company_el = li.find_element(By.XPATH, ".//span[contains(@class,'t-14') and contains(@class,'t-normal')]")
                company = safe_get_text(company_el)
            except NoSuchElementException:
                pass

            try:
                date_el = li.find_element(By.XPATH, ".//span[contains(@class,'t-14') and (contains(.,'Present') or contains(.,'–'))]")
                date_range = safe_get_text(date_el)
            except NoSuchElementException:
                pass

            smalls = li.find_elements(By.CSS_SELECTOR, "span.t-14.t-normal.t-black--light")
            if len(smalls) >= 2:
                location = safe_get_text(smalls[-1])

            try:
                desc_el = li.find_element(By.XPATH, ".//div[contains(@class,'inline-show-more-text')]")
                desc = safe_get_text(desc_el)
            except NoSuchElementException:
                pass

            if any([title, company, date_range, location, desc]):
                exps.append({
                    "title": title,
                    "company": company,
                    "date_range": date_range,
                    "location": location,
                    "description": desc,
                })
        except Exception:
            continue

    return exps


def scrape_people(driver, keyword, max_pages, log, stop_flag):
    open_people_search(driver, keyword)

    results = []
    page = 1

    while not stop_flag[0]:
        log(f"🔎 Page {page}: scanning results…")

        # Always make sure we are on the results page and it's populated
        scroll_results_page(driver, passes=2)
        cards = extract_result_cards(driver)
        if not cards:
            log("⚠️ No cards found; rescrolling and retrying…")
            scroll_results_page(driver, passes=3)
            cards = extract_result_cards(driver)
        log(f"• Found {len(cards)} result cards on this page")

        # Snapshot the result page URL and the profile links NOW to avoid stale elements
        results_url = driver.current_url
        links = []
        for card in cards:
            link = get_profile_link_from_card(card)
            if link and "/in/" in link:
                links.append(link)

        # Visit each profile in the SAME TAB then navigate back to the results page URL
        for idx, link in enumerate(links, start=1):
            if stop_flag[0]:
                break
            try:
                driver.get(link)
                sleep_jitter(1.1, 1.7)

                profile_basic = extract_profile_basic(driver)
                exps = extract_experiences(driver, link)
                profile_basic["profile_url"] = link
                profile_basic["experiences"] = exps

                results.append(profile_basic)
                log(f"  ✔️ [{idx}/{len(links)}] {profile_basic.get('name') or 'Unknown'} — {link}")
            except Exception as e:
                log(f"  ⚠️ Error opening/extracting profile: {e}")
            finally:
                # Go back to the results page to continue/paginate
                try:
                    driver.get(results_url)
                    sleep_jitter(0.8, 1.2)
                except Exception:
                    pass

        # Pagination: click Next if exists
        if max_pages and page >= max_pages:
            log("⏹️ Reached max pages limit.")
            break

        try:
            # Try multiple patterns (English/Indonesian, span or aria-label)
            next_xpath = (
                "//button[contains(@aria-label,'Next') and not(@disabled)] | "
                "//span[normalize-space()='Next']/ancestor::button[not(@disabled)] | "
                "//button[.//span[contains(normalize-space(.),'Next')] and not(@disabled)] | "
                "//button[@aria-label='Berikutnya' and not(@disabled)] | "
                "//span[normalize-space()='Berikutnya']/ancestor::button[not(@disabled)]"
            )
            next_btn = driver.find_element(By.XPATH, next_xpath)
            driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", next_btn)
            sleep_jitter(0.6, 1.0)
            next_btn.click()
            sleep_jitter(1.2, 1.8)
            page += 1
        except NoSuchElementException:
            log("✅ No more pages (Next button not found/disabled). Done.")
            break
        except Exception as e:
            log(f"⚠️ Pagination error: {e}")
            break

    return results


def format_experiences(exps):
  lines = []
  for e in exps or []:
    parts = []
    title = (e.get("title") or "").strip()
    company = (e.get("company") or "").strip()
    date_range = (e.get("date_range") or "").strip()
    location = (e.get("location") or "").strip()
    desc = (e.get("description") or "").strip()

    if title:
      parts.append(title)
    if company:
      parts.append(f"at {company}")

    head = " ".join(parts).strip()
    if date_range:
      head += f" ({date_range})"
    if location:
      head += f" — {location}"
    if desc:
      head += f": {desc}"

    if head:
      lines.append(f"- {head}")

  return "\n".join(lines)


def results_to_dataframe(results):
    rows = []
    for r in results:
        rows.append({
            "Name": r.get("name", ""),
            "Headline": r.get("headline", ""),
            "Location": r.get("location", ""),
            # Removed "Current Company" as requested
            "About": r.get("about", ""),
            "Profile URL": r.get("profile_url", ""),
            "Experiences": format_experiences(r.get("experiences", [])),
        })
    # Column order
    df = pd.DataFrame(rows, columns=["Name","Headline","Location","About","Profile URL","Experiences"])
    return df


# -----------------------------
# Tkinter UI
# -----------------------------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("LinkedIn People Scraper (Free UI - Tkinter)")
        self.geometry("820x600")

        self.driver = None
        self.worker = None
        self.stop_flag = [False]

        self.create_widgets()

    def create_widgets(self):
        frm = ttk.Frame(self)
        frm.pack(fill=tk.X, padx=10, pady=10)

        ttk.Label(frm, text="LinkedIn Email").grid(row=0, column=0, sticky=tk.W)
        self.email_var = tk.StringVar()
        ttk.Entry(frm, textvariable=self.email_var, width=40).grid(row=0, column=1, sticky=tk.W)

        ttk.Label(frm, text="Password").grid(row=1, column=0, sticky=tk.W)
        self.pwd_var = tk.StringVar()
        ttk.Entry(frm, textvariable=self.pwd_var, show="*", width=40).grid(row=1, column=1, sticky=tk.W)

        ttk.Label(frm, text="Keyword").grid(row=2, column=0, sticky=tk.W)
        self.kw_var = tk.StringVar(value="Software Engineer Indonesia")
        ttk.Entry(frm, textvariable=self.kw_var, width=40).grid(row=2, column=1, sticky=tk.W)

        ttk.Label(frm, text="Max Pages").grid(row=3, column=0, sticky=tk.W)
        self.pages_var = tk.StringVar(value="3")
        ttk.Entry(frm, textvariable=self.pages_var, width=10).grid(row=3, column=1, sticky=tk.W)

        self.headless_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(frm, text="Headless (hide browser)", variable=self.headless_var).grid(row=4, column=1, sticky=tk.W)

        # Save options
        save_frm = ttk.Frame(self)
        save_frm.pack(fill=tk.X, padx=10, pady=6)
        ttk.Label(save_frm, text="Save as:").grid(row=0, column=0, sticky=tk.W)
        self.fmt_var = tk.StringVar(value="csv")
        ttk.Radiobutton(save_frm, text="CSV", value="csv", variable=self.fmt_var).grid(row=0, column=1, sticky=tk.W)
        ttk.Radiobutton(save_frm, text="Excel", value="xlsx", variable=self.fmt_var).grid(row=0, column=2, sticky=tk.W)

        ttk.Label(save_frm, text="Output file:").grid(row=1, column=0, sticky=tk.W)
        self.out_var = tk.StringVar(value="linkedin_results.csv")
        ttk.Entry(save_frm, textvariable=self.out_var, width=50).grid(row=1, column=1, sticky=tk.W)
        ttk.Button(save_frm, text="Browse…", command=self.browse_save).grid(row=1, column=2, padx=5)

        # Buttons
        btn_frm = ttk.Frame(self)
        btn_frm.pack(fill=tk.X, padx=10, pady=6)
        ttk.Button(btn_frm, text="Start", command=self.on_start).pack(side=tk.LEFT)
        ttk.Button(btn_frm, text="Stop", command=self.on_stop).pack(side=tk.LEFT, padx=8)

        # Log area
        self.log = ScrolledText(self, height=20)
        self.log.pack(fill=tk.BOTH, expand=True, padx=10, pady=8)
        self.log.configure(state=tk.DISABLED)

        # Style
        for child in frm.winfo_children():
            child.grid_configure(padx=5, pady=5)
        for child in save_frm.winfo_children():
            child.grid_configure(padx=5, pady=5)

    def browse_save(self):
        fmt = self.fmt_var.get()
        defaultextension = ".csv" if fmt == "csv" else ".xlsx"
        filetypes = [("CSV files", "*.csv")] if fmt == "csv" else [("Excel files", "*.xlsx")]
        path = filedialog.asksaveasfilename(defaultextension=defaultextension, filetypes=filetypes)
        if path:
            self.out_var.set(path)

    def append_log(self, msg):
        self.log.configure(state=tk.NORMAL)
        self.log.insert(tk.END, str(msg) + "\n")
        self.log.see(tk.END)
        self.log.configure(state=tk.DISABLED)
        self.update_idletasks()

    def on_start(self):
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("Info", "Scraping already running…")
            return

        email = self.email_var.get().strip()
        pwd = self.pwd_var.get().strip()
        kw = self.kw_var.get().strip()
        try:
            pages = int(self.pages_var.get().strip()) if self.pages_var.get().strip() else 1
        except ValueError:
            pages = 1

        if not email or not pwd or not kw:
            messagebox.showerror("Missing", "Please fill Email, Password, and Keyword")
            return

        headless = self.headless_var.get()
        fmt = self.fmt_var.get()
        out_path = self.out_var.get().strip() or ("linkedin_results.csv" if fmt == "csv" else "linkedin_results.xlsx")

        # Ensure extension matches chosen format
        if fmt == "csv" and not out_path.lower().endswith('.csv'):
            out_path += '.csv'
        if fmt == "xlsx" and not out_path.lower().endswith('.xlsx'):
            out_path += '.xlsx'

        self.stop_flag[0] = False

        def work(email_, pwd_, kw_, pages_, fmt_, headless_, out_path_):
            driver = None
            try:
                self.append_log("Launching Chrome…")
                driver = setup_driver(headless=headless_)
                self.driver = driver

                self.append_log("Logging in to LinkedIn…")
                linkedin_login(driver, email_, pwd_, self.append_log)

                self.append_log(f"Searching people for: '{kw_}'")
                results = scrape_people(driver, kw_, pages_, self.append_log, self.stop_flag)
                self.append_log(f"Collected {len(results)} profiles.")

                df = results_to_dataframe(results)
                if fmt_ == "csv":
                    df.to_csv(out_path_, index=False)
                else:
                    df.to_excel(out_path_, index=False)

                self.append_log(f"✅ Saved results to {out_path_}")

            except Exception as e:
                self.append_log("❌ Error: " + str(e))
                self.append_log(traceback.format_exc())
            finally:
                try:
                    if driver:
                        driver.quit()
                except Exception:
                    pass
                self.driver = None
                self.append_log("Browser closed.")

        # pass values into the thread so there's no scope issue
        self.worker = threading.Thread(target=work, args=(email, pwd, kw, pages, fmt, headless, out_path), daemon=True)
        self.worker.start()

    def on_stop(self):
        self.stop_flag[0] = True
        self.append_log("⏹️ Stop requested. Finishing current step…")


if __name__ == "__main__":
    app = App()
    app.mainloop()
