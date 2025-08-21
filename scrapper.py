import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import pandas as pd

# Setup Chrome driver
service = Service(ChromeDriverManager().install())
driver = webdriver.Chrome(service=service)

# Login LinkedIn (ganti dengan credential Anda)
def linkedin_login(email, password):
    driver.get("https://www.linkedin.com/login")
    time.sleep(2)
    
    driver.find_element(By.ID, "username").send_keys(email)
    driver.find_element(By.ID, "password").send_keys(password)
    driver.find_element(By.XPATH, "//button[@type='submit']").click()
    time.sleep(3)

# Ganti dengan credential Anda
linkedin_login("thejukius@gmail.com", ".i3D9Sa4QC)C@5z")

# Pencarian LinkedIn
search_query = "kontraktor surabaya"  # Ganti dengan pencarian Anda
search_url = f"https://www.linkedin.com/search/results/people/?keywords={search_query.replace(' ', '%20')}"
driver.get(search_url)
time.sleep(3)

# Scroll untuk memuat lebih banyak hasil
for _ in range(3):
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    time.sleep(2)

# Scraping data
profiles = []
profile_elements = driver.find_elements(By.CSS_SELECTOR, ".entity-result__item")

for element in profile_elements:
    try:
        name = element.find_element(By.CSS_SELECTOR, ".entity-result__title-text a").text.strip()
        title = element.find_element(By.CSS_SELECTOR, ".entity-result__primary-subtitle").text.strip()
        location = element.find_element(By.CSS_SELECTOR, ".entity-result__secondary-subtitle").text.strip()
        profile_url = element.find_element(By.CSS_SELECTOR, ".entity-result__title-text a").get_attribute("href").split('?')[0]
        
        profiles.append({
            'Name': name,
            'Title': title,
            'Location': location,
            'Profile URL': profile_url
        })
    except Exception as e:
        print(f"Error extracting data: {e}")

# Simpan ke Excel
df = pd.DataFrame(profiles)
df.to_excel("linkedin_search_results.xlsx", index=False)
print(f"Data disimpan ke linkedin_search_results.xlsx dengan {len(df)} hasil")

# Tutup browser
driver.quit()