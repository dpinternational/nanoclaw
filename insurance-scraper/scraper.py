"""
Insurance Agent Scraper v2 - Autonomous 50-State Pipeline
Based on SBS_Scraper_MAC_Complete_v2 engine.
Searches NAIC SOLAR: A-Z, AA-ZZ, AAA-ZZZ (18,278 prefixes per state)
Auto-advances through states, resumes from exact prefix, crash-recovers.
All progress tracked in Supabase.
"""

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from supabase import create_client, Client
from datetime import datetime
import time
import os
import re
import string
import logging
import json
import sys
import random
import traceback

from dotenv import load_dotenv
load_dotenv()

# ─── Configuration ──────────────────────────────────────────────
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
HEADLESS = os.getenv("HEADLESS", "true").lower() == "true"
PROXY_URL = os.getenv("PROXY_URL", "")  # e.g. socks5://user:pass@host:port
INTER_STATE_SLEEP = int(os.getenv("INTER_STATE_SLEEP", "3600"))  # 1 hour between states
WORKER_ID = os.getenv("WORKER_ID") or f"worker-{os.uname().nodename}"
RUNNING_STALE_MINUTES = int(os.getenv("RUNNING_STALE_MINUTES", "120"))
CLAIM_RETRY_SLEEP = float(os.getenv("CLAIM_RETRY_SLEEP", "2"))
ENABLE_MONTHLY_RESET = os.getenv("ENABLE_MONTHLY_RESET", "false").lower() == "true"
MAX_PREFIX_RETRIES = 3
MIN_SEARCH_DELAY = 2.0
MAX_SEARCH_DELAY = 5.0
MIN_DETAIL_DELAY = 0.5
MAX_DETAIL_DELAY = 1.5

NAIC_SOLAR_URL = "https://sbs.naic.org/solar-external-lookup/"

# States available on SBS/NAIC SOLAR (not all 50 are listed)
SBS_STATES = [
    "Alabama", "Alaska", "Arizona", "Arkansas", "Connecticut", "Delaware",
    "District of Columbia", "Florida", "Guam", "Hawaii", "Idaho", "Illinois",
    "Iowa", "Kansas", "Maryland", "Massachusetts", "Missouri", "Montana",
    "Nebraska", "New Hampshire", "New Jersey", "New Mexico", "North Carolina",
    "North Dakota", "Oklahoma", "Oregon", "Puerto Rico", "Rhode Island",
    "South Carolina", "South Dakota", "Tennessee", "Vermont", "Virgin Islands",
    "Virginia", "West Virginia", "Wisconsin"
]

# ─── Logging ────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('scraper.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# ─── Supabase Client ───────────────────────────────────────────
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
logger.info("Connected to Supabase")


def generate_alphabet_prefixes():
    """Generate smart prefixes: A-Z (26) + AA-ZZ (676) = 702 total.
    Three-letter combos are only used as drill-downs when a two-letter
    prefix hits the 200-page limit (handled in search_prefix)."""
    prefixes = []
    for c in string.ascii_uppercase:
        prefixes.append(c)
    for c1 in string.ascii_uppercase:
        for c2 in string.ascii_uppercase:
            prefixes.append(c1 + c2)
    return prefixes


def generate_drilldown_prefixes(two_letter):
    """Generate AAA-AAZ drill-downs for a two-letter prefix that hit page limit."""
    return [two_letter + c for c in string.ascii_uppercase]


ALL_PREFIXES = generate_alphabet_prefixes()
TOTAL_PREFIXES = len(ALL_PREFIXES)


def rand_delay(min_s, max_s):
    """Randomized sleep to appear human"""
    time.sleep(random.uniform(min_s, max_s))


# ─── State Queue Manager ───────────────────────────────────────
class StateQueue:
    """Manages scrape_runs table in Supabase for state-level progress"""

    @staticmethod
    def initialize():
        """Pre-populate scrape_runs with all SBS states if not already present"""
        existing = supabase.table("scrape_runs").select("state").execute()
        existing_states = {r['state'] for r in existing.data}

        for state in SBS_STATES:
            if state not in existing_states:
                supabase.table("scrape_runs").insert({
                    'state': state,
                    'status': 'pending',
                    'last_prefix': 'A',
                    'prefixes_completed': 0,
                    'total_prefixes': TOTAL_PREFIXES,
                    'total_found': 0,
                    'qualified': 0,
                    'saved': 0,
                    'errors': 0,
                    'updated_at': datetime.now().isoformat()
                }).execute()
                logger.info(f"  Added state: {state}")

        logger.info(f"State queue initialized ({len(SBS_STATES)} states)")

    @staticmethod
    def recycle_stale_running(stale_minutes: int):
        """Return stale running states back to pending so another worker can claim them."""
        cutoff = datetime.now().timestamp() - (stale_minutes * 60)
        cutoff_iso = datetime.fromtimestamp(cutoff).isoformat()
        try:
            recycled = supabase.table("scrape_runs").update({
                'status': 'pending',
                'updated_at': datetime.now().isoformat(),
            }).eq("status", "running").lt("updated_at", cutoff_iso).execute()
            if recycled.data:
                states = [r.get('state') for r in recycled.data]
                logger.warning(f"Recycled stale running states ({len(states)}): {states}")
        except Exception as e:
            logger.warning(f"Could not recycle stale running states: {e}")

    @staticmethod
    def queue_counts():
        """Return counts of pending/running/completed states."""
        counts = {'pending': 0, 'running': 0, 'completed': 0}
        for status in counts.keys():
            try:
                result = supabase.table("scrape_runs").select("id").eq("status", status).execute()
                counts[status] = len(result.data or [])
            except Exception:
                pass
        return counts

    @staticmethod
    def claim_next_state(worker_id: str):
        """Atomically claim one pending state for this worker.

        Multiple workers can call this safely. Only one worker can flip a row
        from pending->running because the update is conditional on current status.
        """
        StateQueue.recycle_stale_running(RUNNING_STALE_MINUTES)

        while True:
            pending = supabase.table("scrape_runs") \
                .select("*") \
                .eq("status", "pending") \
                .order("state") \
                .limit(1) \
                .execute()

            if not pending.data:
                return None

            candidate = pending.data[0]
            now_iso = datetime.now().isoformat()

            claim = supabase.table("scrape_runs").update({
                'status': 'running',
                'started_at': candidate.get('started_at') or now_iso,
                'updated_at': now_iso,
            }).eq("id", candidate['id']).eq("status", "pending").execute()

            if claim.data:
                logger.info(
                    f"Worker {worker_id} claimed state: {candidate['state']} "
                    f"from prefix '{candidate.get('last_prefix') or 'A'}'"
                )
                return claim.data[0]

            # Lost race to another worker; retry quickly.
            time.sleep(CLAIM_RETRY_SLEEP + random.uniform(0.1, 0.9))
    @staticmethod
    def update_progress(state_id, prefix, stats):
        """Update progress after each prefix"""
        prefix_index = ALL_PREFIXES.index(prefix) + 1 if prefix in ALL_PREFIXES else 0
        supabase.table("scrape_runs").update({
            'last_prefix': prefix,
            'prefixes_completed': prefix_index,
            'total_found': stats.get('total_found', 0),
            'qualified': stats.get('qualified', 0),
            'saved': stats.get('saved', 0),
            'errors': stats.get('errors', 0),
            'updated_at': datetime.now().isoformat()
        }).eq("id", state_id).execute()

    @staticmethod
    def complete_state(state_id, stats):
        """Mark state as completed"""
        supabase.table("scrape_runs").update({
            'status': 'completed',
            'total_found': stats.get('total_found', 0),
            'qualified': stats.get('qualified', 0),
            'saved': stats.get('saved', 0),
            'errors': stats.get('errors', 0),
            'prefixes_completed': TOTAL_PREFIXES,
            'completed_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        }).eq("id", state_id).execute()

    @staticmethod
    def fail_state(state_id, stats):
        """Mark state as failed (will be retried)"""
        supabase.table("scrape_runs").update({
            'status': 'failed',
            'total_found': stats.get('total_found', 0),
            'qualified': stats.get('qualified', 0),
            'saved': stats.get('saved', 0),
            'errors': stats.get('errors', 0),
            'updated_at': datetime.now().isoformat()
        }).eq("id", state_id).execute()


# ─── Main Scraper Engine ───────────────────────────────────────
class InsuranceAgentScraper:
    """Core scraper engine — based on SBS_Scraper_MAC_Complete_v2"""

    def __init__(self, state_name, headless=True):
        self.base_url = NAIC_SOLAR_URL
        self.state = state_name
        self.loa = "Life"
        self.headless = headless
        self.driver = None
        self.seen_npns = set()
        self.stats = {
            'total_found': 0,
            'qualified': 0,
            'saved': 0,
            'saved_with_appointments': 0,
            'saved_without_appointments': 0,
            'new_licensees': 0,
            'duplicates': 0,
            'skipped': 0,
            'errors': 0,
            'appointments_saved': 0,
            'prefixes_searched': 0
        }
        self._load_existing_npns()

    def _load_existing_npns(self):
        """Load NPNs already in DB to skip duplicates"""
        try:
            all_npns = set()
            offset = 0
            batch_size = 1000
            while True:
                result = supabase.table("agents") \
                    .select("npn") \
                    .eq("state", self.state) \
                    .range(offset, offset + batch_size - 1) \
                    .execute()
                for row in result.data:
                    if row.get('npn'):
                        all_npns.add(row['npn'])
                if len(result.data) < batch_size:
                    break
                offset += batch_size

            self.seen_npns = all_npns
            logger.info(f"Loaded {len(self.seen_npns)} existing NPNs for {self.state}")
        except Exception as e:
            logger.warning(f"Could not load existing NPNs: {e}")

    def _init_driver(self):
        """Initialize Chrome with crash recovery"""
        logger.info("Initializing Chrome browser...")
        options = Options()
        if self.headless:
            options.add_argument('--headless')
        options.add_argument('--window-size=1920,1080')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        options.add_argument('--disable-extensions')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        prefs = {"profile.default_content_setting_values.notifications": 2}
        options.add_experimental_option("prefs", prefs)

        # Auto-detect Chrome binary
        for path in [
            os.environ.get('CHROME_BIN', ''),
            '/usr/bin/google-chrome-stable',
            '/usr/bin/google-chrome',
            '/opt/google/chrome/google-chrome',
            '/usr/bin/chromium',
            '/usr/bin/chromium-browser',
        ]:
            if path and os.path.exists(path):
                options.binary_location = path
                logger.info(f"Using Chrome at: {path}")
                break

        # User-agent to avoid bot detection
        options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36')

        # Proxy support (use IP whitelist on provider so no auth needed)
        if PROXY_URL:
            # Strip auth from URL if present — relies on IP whitelist
            proxy_no_auth = re.sub(r'https?://[^@]+@', 'http://', PROXY_URL)
            options.add_argument(f'--proxy-server={proxy_no_auth}')
            logger.info(f"Using proxy: {proxy_no_auth}")

        # Prefer OS-packaged chromedriver (matches installed chromium, correct CPU arch)
        chromedriver_path = None
        for path in ['/usr/bin/chromedriver', '/usr/local/bin/chromedriver']:
            if os.path.exists(path):
                chromedriver_path = path
                logger.info(f"Using system ChromeDriver at: {path}")
                break

        # Fallback to webdriver-manager only if system driver is unavailable
        if not chromedriver_path:
            try:
                from webdriver_manager.chrome import ChromeDriverManager
                chromedriver_path = ChromeDriverManager().install()
                logger.info("Using ChromeDriver from webdriver-manager")
            except Exception as e:
                logger.warning(f"webdriver-manager unavailable: {e}")

        service = Service(chromedriver_path) if chromedriver_path else None
        if service:
            self.driver = webdriver.Chrome(service=service, options=options)
        else:
            self.driver = webdriver.Chrome(options=options)

        self.driver.implicitly_wait(10)
        self.driver.set_page_load_timeout(60)
        logger.info("Chrome initialized")

    def _is_session_valid(self):
        """Check if the current Chrome session is still valid"""
        try:
            if self.driver:
                _ = self.driver.current_url
                return True
        except:
            pass
        return False

    def _recover_session(self):
        """Recover from an invalid session by reinitializing Chrome"""
        logger.warning("Session invalid - recovering...")
        try:
            if self.driver:
                try:
                    self.driver.quit()
                except:
                    pass
                self.driver = None
        except:
            pass
        time.sleep(2)
        self._init_driver()
        logger.info("Session recovered")

    def _restart_driver(self):
        """Restart Chrome after crash"""
        logger.warning("Restarting Chrome driver...")
        self.close()
        time.sleep(3)
        self._init_driver()

    def _wait_overlay_gone(self, timeout=30):
        try:
            WebDriverWait(self.driver, timeout).until(
                EC.invisibility_of_element_located((By.CSS_SELECTOR, ".overlay"))
            )
        except:
            pass

    def _safe_click(self, element):
        try:
            element.click()
        except:
            self.driver.execute_script("arguments[0].click();", element)

    def _extract_text(self, xpath):
        """Extract text from element by xpath, return empty string if not found"""
        try:
            return self.driver.find_element(By.XPATH, xpath).text.strip()
        except:
            return ""

    def _select_if_present(self, element_id, visible_text):
        """Select a dropdown option with fallback matching"""
        d = self.driver
        try:
            elem = None
            try:
                elem = d.find_element(By.ID, element_id)
            except:
                try:
                    elem = d.find_element(By.NAME, element_id)
                except:
                    pass

            if not elem:
                return

            sel = Select(elem)

            # Exact match
            try:
                sel.select_by_visible_text(visible_text)
                rand_delay(0.2, 0.4)
                return
            except:
                pass

            # Partial match (case-insensitive)
            for opt in sel.options:
                if visible_text.lower() in opt.text.strip().lower():
                    sel.select_by_visible_text(opt.text.strip())
                    rand_delay(0.2, 0.4)
                    return

            # By value
            try:
                sel.select_by_value(visible_text)
                rand_delay(0.2, 0.4)
            except:
                pass

        except Exception as e:
            logger.debug(f"Select {element_id}: {str(e)[:40]}")

    def _safe_click_advanced(self):
        """Expand Advanced Criteria section"""
        d = self.driver
        w = WebDriverWait(d, 20)
        try:
            self._wait_overlay_gone()
            btn = w.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button.advanced-criteria")))
            d.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
            rand_delay(0.2, 0.4)
            try:
                btn.click()
            except:
                d.execute_script("arguments[0].click();", btn)
            self._wait_overlay_gone()
            rand_delay(0.3, 0.6)
            logger.debug("Advanced Criteria expanded")
        except Exception as e:
            logger.debug(f"Advanced button: {str(e)[:40]}")

    def _select_loa(self):
        """Select Line of Authority dropdown"""
        d = self.driver
        try:
            try:
                sel = Select(d.find_element(By.ID, "loaType"))
            except:
                sel = Select(d.find_element(By.NAME, "lineOfAuthority"))

            for opt in sel.options:
                if opt.text.strip().lower() == self.loa.lower():
                    sel.select_by_visible_text(opt.text.strip())
                    rand_delay(0.2, 0.4)
                    return

            for opt in sel.options:
                if self.loa.lower() in opt.text.strip().lower():
                    sel.select_by_visible_text(opt.text.strip())
                    rand_delay(0.2, 0.4)
                    return

        except Exception as e:
            logger.debug(f"LOA selection: {str(e)[:40]}")

    def _accept_terms(self):
        """Accept the terms checkbox"""
        d = self.driver
        self._wait_overlay_gone()
        d.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        rand_delay(0.3, 0.6)
        checkbox = None
        for locator in [
            (By.ID, "agree"),
            (By.XPATH, "//input[@type='checkbox']"),
            (By.XPATH, "//input[contains(@id,'agree') or contains(@name,'agree')]")
        ]:
            try:
                checkbox = d.find_element(*locator)
                break
            except:
                continue
        if checkbox:
            d.execute_script("arguments[0].scrollIntoView({block:'center'});", checkbox)
            rand_delay(0.1, 0.3)
            try:
                if not checkbox.is_selected():
                    try:
                        checkbox.click()
                    except:
                        d.execute_script("arguments[0].click();", checkbox)
                if not checkbox.is_selected():
                    d.execute_script(
                        "arguments[0].checked = true; arguments[0].dispatchEvent(new Event('change'));",
                        checkbox
                    )
            except:
                logger.warning("Could not toggle terms checkbox")

    def _safe_submit_search(self):
        """Submit the search form"""
        d = self.driver
        self._wait_overlay_gone()
        btn = None
        try:
            btn = d.find_element(By.CSS_SELECTOR, "button[type='submit']")
        except:
            try:
                for b in d.find_elements(By.TAG_NAME, "button"):
                    if "search" in b.text.lower():
                        btn = b
                        break
            except:
                pass
        if not btn:
            raise RuntimeError("Search button not found")

        d.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
        rand_delay(0.1, 0.3)
        try:
            btn.click()
        except:
            d.execute_script("arguments[0].click();", btn)
        rand_delay(0.3, 0.6)
        self._wait_overlay_gone()

    def _setup_search(self, last_name_prefix=""):
        """Navigate to NAIC SOLAR and set up search with Advanced Criteria"""
        d = self.driver
        w = WebDriverWait(d, 30)

        d.get(self.base_url)
        w.until(EC.presence_of_element_located((By.ID, "jurisdiction")))
        self._wait_overlay_gone()
        rand_delay(1.0, 2.0)

        # Select state
        Select(d.find_element(By.ID, "jurisdiction")).select_by_visible_text(self.state)
        rand_delay(0.3, 0.6)

        # Search type: Licensee
        Select(d.find_element(By.ID, "searchType")).select_by_visible_text("Licensee")
        rand_delay(0.3, 0.6)

        # Expand Advanced Criteria
        self._safe_click_advanced()

        # Set advanced filters
        self._select_if_present("licenseType", "Insurance Producer")
        self._select_if_present("licenseStatus", "Active")
        self._select_if_present("residentLicense", "Yes")
        # No LOA filter — capture all active producers regardless of license type

        # Last name prefix
        if last_name_prefix:
            try:
                ln = d.find_element(By.ID, "lastName")
                ln.clear()
                ln.send_keys(last_name_prefix)
            except:
                pass

        # Accept terms
        self._accept_terms()

        # Submit
        self._safe_submit_search()

        # Wait for results
        try:
            WebDriverWait(d, 45).until(
                lambda drv: len(drv.find_elements(By.TAG_NAME, "table")) > 0
                or "no results" in drv.page_source.lower()
                or "no records" in drv.page_source.lower()
            )
        except TimeoutException:
            logger.warning("Timeout waiting for results")

        rand_delay(MIN_SEARCH_DELAY, MAX_SEARCH_DELAY)
        return True

    def _extract_agents_from_page(self):
        """Extract agent names and detail URLs from current results page"""
        agents = []
        d = self.driver
        try:
            rows = d.find_elements(By.XPATH, "//table//tr[td]")
            for row in rows:
                try:
                    link = row.find_element(By.TAG_NAME, "a")
                    agents.append({
                        'name': link.text.strip(),
                        'detail_url': link.get_attribute('href')
                    })
                except:
                    continue
        except:
            pass
        return agents

    def _go_to_next_page(self):
        """Navigate to next results page using pagination"""
        d = self.driver
        try:
            d.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            for link in d.find_elements(By.CLASS_NAME, "page-link"):
                if link.text.strip().lower() == 'next':
                    parent = link.find_element(By.XPATH, "..")
                    cls = (parent.get_attribute('class') or '').lower()
                    if 'disabled' not in cls:
                        try:
                            link.click()
                        except:
                            d.execute_script("arguments[0].click();", link)
                        rand_delay(0.5, 1.0)
                        self._wait_overlay_gone()
                        return True
            return False
        except:
            return False

    def _extract_agent_details(self, detail_url):
        """Get full details from agent detail page — multi-fallback extraction"""
        d = self.driver
        d.get(detail_url)

        try:
            WebDriverWait(d, 15).until(
                EC.presence_of_element_located(
                    (By.XPATH, "//h4[contains(text(),'Licensee Demographics')] | //div[contains(@class,'panel')]")
                )
            )
        except:
            pass
        rand_delay(MIN_DETAIL_DELAY, MAX_DETAIL_DELAY)

        # Speed optimization: set implicit wait to 0 for fast element checks
        d.implicitly_wait(0)

        page = d.page_source

        # ── Email ──
        email = ''
        for xpath in [
            "//tr[td[contains(text(),'Business Email')]]/td[2]",
            "//td[text()='Business Email']/following-sibling::td",
            "//tr[td='Business Email']/td[last()]",
            "//th[contains(text(),'E-mail')]/following-sibling::td",
            "//td[contains(text(),'Business Email')]/following-sibling::td",
        ]:
            email = self._extract_text(xpath)
            if email and '@' in email:
                break

        if not email or '@' not in email:
            match = re.search(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', page)
            if match:
                candidate = match.group(0)
                if not any(x in candidate.lower() for x in ['naic.org', 'example.com', 'test.com']):
                    email = candidate

        # ── Phone ──
        phone = ''
        for xpath in [
            "//tr[td[contains(text(),'Business Primary Phone')]]/td[2]",
            "//td[text()='Business Primary Phone']/following-sibling::td",
            "//td[contains(text(),'Business Primary Phone')]/following-sibling::td",
            "//tr[td='Business Primary Phone']/td[last()]",
        ]:
            phone = self._extract_text(xpath)
            if phone and re.search(r'\d', phone):
                break

        # ── License Expiration ──
        expiration = ''
        for xpath in [
            "//table[.//th[contains(text(),'Expiration Date')]]//tr[td][1]/td[5]",
            "//th[text()='Expiration Date']/ancestor::thead/following-sibling::tbody/tr[1]/td[5]",
            "//tr[td[contains(text(),'Insurance Producer')]]/td[5]",
            "//tr[td[contains(text(),'Active')]]/td[last()]",
            "//th[contains(text(),'Expiration Date')]/following-sibling::td",
        ]:
            expiration = self._extract_text(xpath)
            if expiration and re.search(r'\d{1,2}/\d{1,2}/\d{2,4}', expiration):
                break

        if not expiration or not re.search(r'\d{1,2}/\d{1,2}/\d{2,4}', expiration):
            match = re.search(r'Expiration Date</th>.*?(\d{1,2}/\d{1,2}/\d{4})', page, re.IGNORECASE | re.DOTALL)
            if match:
                expiration = match.group(1)

        # ── NPN ──
        npn = ''
        # The NPN on NAIC is in format: <label>NPN: </label> 7375074
        # Use regex on raw HTML to handle tags between label and value
        npn_match = re.search(r'NPN[:\s]*(?:</\w+>)?\s*(\d{5,})', page)
        if npn_match:
            npn = npn_match.group(1)
        if not npn:
            # Fallback: try XPaths
            for xpath in [
                "//*[contains(text(),'NPN:')]/..",
                "//*[contains(text(),'NPN:')]",
            ]:
                text = self._extract_text(xpath)
                if text:
                    m = re.search(r'(\d{5,})', text)
                    if m:
                        npn = m.group(1)
                        break

        # ── Address ──
        address = ''
        for xpath in [
            "//th[contains(text(),'Business Address')]/following-sibling::td",
            "//th[contains(text(),'Address')]/following-sibling::td",
        ]:
            address = self._extract_text(xpath)
            if address:
                break

        # ── License Status ──
        status = ''
        for xpath in [
            "//th[contains(text(),'License Status')]/following-sibling::td",
            "//th[contains(text(),'Status')]/following-sibling::td",
        ]:
            status = self._extract_text(xpath)
            if status:
                break

        # ── Effective Date ──
        effective = ''
        for xpath in [
            "//th[contains(text(),'Effective Date')]/following-sibling::td",
            "//th[contains(text(),'Effective')]/following-sibling::td",
        ]:
            effective = self._extract_text(xpath)
            if effective:
                break

        # ── Lines of Authority ──
        # Extract from the LOA table on the detail page
        # The LOA section lists authority types like "Life", "Accident & Health", etc.
        loa = ''
        try:
            # Click LOA section to expand
            for el in d.find_elements(By.XPATH, "//*[contains(@class,'card-header')]"):
                if 'line of authority' in el.text.lower():
                    d.execute_script("arguments[0].click();", el)
                    time.sleep(2)
                    break

            # Look for LOA values in a table under the LOA section
            loa_values = []
            for el in d.find_elements(By.XPATH, "//table[.//th[contains(text(),'Line of Authority') or contains(text(),'LOA')]]//td"):
                t = el.text.strip()
                # Only keep known LOA types, not company names or dates
                if t in ('Life', 'Accident & Health or Sickness', 'Accident and Health or Sickness',
                         'Property', 'Casualty', 'Variable Life and Variable Annuity',
                         'Personal Lines', 'Surplus Lines', 'Title', 'Travel',
                         'Credit', 'Bail Bonds', 'Surety', 'Limited Line Credit Insurance'):
                    if t not in loa_values:
                        loa_values.append(t)
            loa = ', '.join(loa_values) if loa_values else ''
        except:
            pass

        # ── Appointments (expand collapsed section first) ──
        appointments = self._extract_appointments()

        # Restore implicit wait
        d.implicitly_wait(10)

        return {
            'npn': npn,
            'email': email,
            'phone': phone,
            'license_expiration': expiration,
            'business_address': address,
            'license_status': status or 'Active',
            'effective_date': effective,
            'loas': loa,
            'appointments': appointments
        }

    def _extract_appointments(self):
        """Extract all appointments — expand collapsed sections first (from SBS v2)"""
        d = self.driver
        appointments = []

        try:
            expanded = False

            # Try clicking Appointments section to expand it
            click_selectors = [
                "//div[contains(@class,'card-header')][contains(.,'Appointments')]",
                "//*[@data-bs-toggle='collapse'][contains(.,'Appointments')]",
                "//*[contains(@data-toggle,'collapse')][contains(.,'Appointments')]",
                "//a[contains(@href,'#') and contains(.,'Appointments')]",
                "//button[contains(@class,'accordion')][contains(.,'Appointments')]",
            ]

            for selector in click_selectors:
                elems = d.find_elements(By.XPATH, selector)
                for elem in elems:
                    try:
                        if elem.is_displayed():
                            d.execute_script("arguments[0].scrollIntoView(true);", elem)
                            d.execute_script("arguments[0].click();", elem)
                            expanded = True
                            break
                    except:
                        continue
                if expanded:
                    break

            # Try collapsed panels if still not expanded
            if not expanded:
                panels = d.find_elements(By.XPATH, "//*[contains(@class,'collapse') and not(contains(@class,'show'))]")
                for panel in panels:
                    try:
                        panel_id = panel.get_attribute('id')
                        if panel_id:
                            toggles = d.find_elements(
                                By.XPATH,
                                f"//*[@data-bs-target='#{panel_id}' or @data-target='#{panel_id}' or @href='#{panel_id}']"
                            )
                            for toggle in toggles:
                                if 'Appointment' in toggle.text:
                                    d.execute_script("arguments[0].click();", toggle)
                                    expanded = True
                                    break
                        if expanded:
                            break
                    except:
                        continue

            # Wait for the appointments table to load (Angular lazy-loads via API)
            if expanded:
                try:
                    WebDriverWait(d, 10).until(
                        lambda drv: len(drv.find_elements(By.XPATH,
                            "//table[.//th[contains(text(),'Company Name')]]")) > 0
                        or "no appointments" in drv.page_source.lower()
                        or "no data" in drv.page_source.lower()
                    )
                except:
                    pass  # Timeout — might genuinely have no appointments

            # Find and parse appointments table
            appt_table = None
            table_xpaths = [
                "//table[.//th[contains(text(),'Company Name')]]",
                "//table[.//th[contains(text(),'NAIC')]]",
                "//*[contains(@id,'appointments') or contains(@id,'Appointments')]//table",
                "//h4[contains(text(),'Appointments')]/following::table[1]",
                "//h5[contains(text(),'Appointments')]/following::table[1]",
                "//*[contains(@class,'card-header')][contains(.,'Appointments')]/following-sibling::*//table",
            ]

            for xpath in table_xpaths:
                tables = d.find_elements(By.XPATH, xpath)
                for table in tables:
                    try:
                        if table.is_displayed():
                            table_text = table.text.lower()
                            if 'company' in table_text or 'naic' in table_text or 'authority' in table_text:
                                appt_table = table
                                break
                    except:
                        continue
                if appt_table:
                    break

            if appt_table:
                rows = appt_table.find_elements(By.XPATH, ".//tbody/tr | .//tr[td]")
                for row in rows:
                    try:
                        cells = row.find_elements(By.TAG_NAME, "td")
                        if len(cells) >= 5:
                            appt = {
                                'company_name': cells[0].text.strip() if len(cells) > 0 else '',
                                'naic_cocode': cells[1].text.strip() if len(cells) > 1 else '',
                                'license_type': cells[2].text.strip() if len(cells) > 2 else '',
                                'line_of_authority': cells[3].text.strip() if len(cells) > 3 else '',
                                'appointment_date': cells[4].text.strip() if len(cells) > 4 else '',
                                'effective_date': cells[5].text.strip() if len(cells) > 5 else '',
                                'expiration_date': cells[6].text.strip() if len(cells) > 6 else ''
                            }
                            if appt['company_name'] or appt['naic_cocode']:
                                appointments.append(appt)
                    except:
                        continue

        except Exception as e:
            logger.debug(f"Appointments error: {str(e)[:50]}")

        return appointments

    def _save_to_supabase(self, name, details):
        """Save agent to Supabase with new licensee detection and scoring"""
        npn = details.get('npn', '')
        appointments = details.get('appointments', [])
        appointments_count = len(appointments)
        is_new_licensee = appointments_count == 0

        if is_new_licensee:
            self.stats['new_licensees'] += 1

        # Calculate initial score
        score = 0
        if details.get('email'):
            score += 10
        if details.get('phone'):
            score += 5
        if is_new_licensee:
            score += 30
        elif appointments_count <= 2:
            score += 15

        try:
            agent_data = {
                'name': name,
                'npn': npn if npn else None,
                'email': details.get('email', ''),
                'phone': details.get('phone', ''),
                'state': self.state,
                'business_address': details.get('business_address', ''),
                'loa': details.get('loas', ''),
                'license_type': 'Insurance Producer',
                'license_status': details.get('license_status', 'Active'),
                'license_expiration': details.get('license_expiration', ''),
                'effective_date': details.get('effective_date', ''),
                'appointments': appointments,
                'appointments_list': appointments,
                'appointments_count': appointments_count,
                'is_new_licensee': is_new_licensee,
                'pipeline_stage': 'scraped',
                'score': score,
                'opted_out': False,
                'scraped_at': datetime.now().isoformat()
            }

            # Upsert: check by NPN first, then by name+state as fallback
            existing = None
            if npn:
                existing = supabase.table("agents").select("id, first_scraped_at, email, email_status").eq("npn", npn).execute()
            if not existing or not existing.data:
                # Fallback: match by name + state
                existing = supabase.table("agents").select("id, first_scraped_at, email, email_status") \
                    .eq("name", name).eq("state", self.state).execute()

            if existing and existing.data:
                existing_row = existing.data[0]
                agent_id = existing_row['id']

                old_email = (existing_row.get('email') or '').strip().lower()
                new_email = (details.get('email') or '').strip().lower()

                # Preserve existing verification unless email changed or status is missing.
                if new_email and (new_email != old_email or not existing_row.get('email_status')):
                    agent_data['email_status'] = 'pending'

                result = supabase.table("agents").update(agent_data).eq("id", agent_id).execute()
            else:
                agent_data['first_scraped_at'] = datetime.now().isoformat()
                agent_data['email_status'] = 'pending' if (details.get('email') or '').strip() else None
                result = supabase.table("agents").insert(agent_data).execute()
                agent_id = result.data[0]['id'] if result.data else None

            # Save appointments to separate table
            if agent_id and appointments:
                try:
                    supabase.table("appointments").delete().eq("agent_id", agent_id).execute()
                except:
                    pass

                for appt in appointments:
                    try:
                        supabase.table("appointments").insert({
                            'agent_id': agent_id,
                            'company_name': appt.get('company_name', ''),
                            'naic_cocode': appt.get('naic_cocode', ''),
                            'license_type': appt.get('license_type', ''),
                            'line_of_authority': appt.get('line_of_authority', ''),
                            'appointment_date': appt.get('appointment_date', ''),
                            'effective_date': appt.get('effective_date', ''),
                            'expiration_date': appt.get('expiration_date', '')
                        }).execute()
                        self.stats['appointments_saved'] += 1
                    except:
                        pass

            if npn:
                self.seen_npns.add(npn)

            self.stats['saved'] += 1

            if appointments:
                self.stats['saved_with_appointments'] += 1
            else:
                self.stats['saved_without_appointments'] += 1

            return appointments

        except Exception as e:
            self.stats['errors'] += 1
            logger.error(f"    Save error: {e}")
            return []

    def scrape_prefix(self, prefix, prefix_num):
        """Scrape all agents for a single last-name prefix"""
        if not self.driver:
            self._init_driver()

        progress_pct = int((prefix_num / TOTAL_PREFIXES) * 100)
        logger.info(f"\n[{prefix_num}/{TOTAL_PREFIXES}] ({progress_pct}%) Searching: '{prefix}' in {self.state}")

        # Retry loop
        for attempt in range(MAX_PREFIX_RETRIES):
            try:
                self._setup_search(prefix)
                break
            except Exception as e:
                logger.warning(f"  Search attempt {attempt + 1}/{MAX_PREFIX_RETRIES} failed: {e}")
                if attempt < MAX_PREFIX_RETRIES - 1:
                    backoff = (attempt + 1) * 5
                    logger.info(f"  Retrying in {backoff}s...")
                    time.sleep(backoff)
                    self._restart_driver()
                else:
                    logger.error(f"  Skipping prefix '{prefix}' after {MAX_PREFIX_RETRIES} failures")
                    self.stats['errors'] += 1
                    return

        self.stats['prefixes_searched'] += 1

        # Check for no results
        page_text = self.driver.page_source.lower()
        if any(t in page_text for t in ["no results", "no records", "0 records"]):
            logger.info(f"  No results for '{prefix}'")
            return

        # Collect all agents across all pages
        all_agents = []
        page_num = 1

        while True:
            agents = self._extract_agents_from_page()
            all_agents.extend(agents)
            logger.info(f"  Page {page_num}: {len(agents)} agents")

            if not self._go_to_next_page():
                break
            page_num += 1
            if page_num > 200:
                logger.warning(f"  Page limit reached for '{prefix}'")
                if len(prefix) == 2:
                    logger.info(f"  Drilling down into {prefix}A-{prefix}Z for more results...")
                    # Process what we have so far, then drill down
                    self._process_agents(all_agents, prefix)
                    for sub_prefix in generate_drilldown_prefixes(prefix):
                        self.search_prefix(sub_prefix)
                    return
                break

        if not all_agents:
            logger.info(f"  No agents found for '{prefix}'")
            return

        self._process_agents(all_agents, prefix)

    def _process_agents(self, all_agents, prefix):
        """Extract details and save agents to Supabase."""
        unique_agents = []
        for agent in all_agents:
            self.stats['total_found'] += 1
            unique_agents.append(agent)

        self.stats['qualified'] += len(unique_agents)
        logger.info(f"  Found {len(unique_agents)} agents, extracting details...")

        for i, agent in enumerate(unique_agents, 1):
            logger.info(f"    [{i}/{len(unique_agents)}] {agent['name']}")

            try:
                details = self._extract_agent_details(agent['detail_url'])

                npn = details.get('npn', '')
                if npn and npn in self.seen_npns:
                    self.stats['duplicates'] += 1
                    logger.info(f"      Skipped duplicate (NPN: {npn})")
                    continue

                appointments = self._save_to_supabase(agent['name'], details)

                appt_count = len(appointments) if appointments else 0
                new_tag = " [NEW LICENSEE]" if appt_count == 0 else ""
                email_tag = f" email:{details.get('email', '')}" if details.get('email') else ""
                logger.info(f"      ✓ Saved ({appt_count} appointments){new_tag}{email_tag}")

            except Exception as e:
                error_str = str(e).lower()
                if 'invalid session id' in error_str or 'no such session' in error_str:
                    logger.warning(f"      Session error - recovering...")
                    self._recover_session()
                else:
                    logger.error(f"      Error: {str(e)[:60]}")
                self.stats['errors'] += 1

            rand_delay(MIN_DETAIL_DELAY, MAX_DETAIL_DELAY)

    def scrape_all(self, start_prefix="A", state_run_id=None):
        """Scrape all agents for this state using A-Z, AA-ZZ, AAA-ZZZ pattern"""
        start_index = 0
        for i, p in enumerate(ALL_PREFIXES):
            if p == start_prefix.upper():
                start_index = i
                break

        remaining = TOTAL_PREFIXES - start_index
        logger.info(f"State: {self.state} | Starting from prefix: {start_prefix} (index {start_index})")
        logger.info(f"Remaining prefixes: {remaining}")

        for idx in range(start_index, TOTAL_PREFIXES):
            prefix = ALL_PREFIXES[idx]

            try:
                self.scrape_prefix(prefix, idx + 1)

                # Update Supabase progress after every prefix
                if state_run_id:
                    StateQueue.update_progress(state_run_id, prefix, self.stats)

            except Exception as e:
                logger.error(f"Error on prefix {prefix}: {e}")
                traceback.print_exc()
                self._restart_driver()
                self.stats['errors'] += 1
                # Still update progress so we don't re-scrape this prefix after crash
                if state_run_id:
                    StateQueue.update_progress(state_run_id, prefix, self.stats)

            # Print stats every 100 prefixes
            if (idx + 1) % 100 == 0:
                self._print_stats()

        logger.info("\n" + "=" * 60)
        logger.info(f"STATE COMPLETE: {self.state}")
        self._print_stats()

    def _print_stats(self):
        logger.info(f"\n--- STATS for {self.state} ---")
        logger.info(f"Prefixes Searched: {self.stats['prefixes_searched']}")
        logger.info(f"Total Found: {self.stats['total_found']}")
        logger.info(f"Qualified: {self.stats['qualified']}")
        logger.info(f"Saved: {self.stats['saved']} (w/appt: {self.stats['saved_with_appointments']}, w/o: {self.stats['saved_without_appointments']})")
        logger.info(f"New Licensees (0 appts): {self.stats['new_licensees']}")
        logger.info(f"Appointments Saved: {self.stats['appointments_saved']}")
        logger.info(f"Duplicates Skipped: {self.stats['duplicates']}")
        logger.info(f"Errors: {self.stats['errors']}")

    def close(self):
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass
            self.driver = None


# ─── Main Loop: Auto-advance through all states ────────────────
def main():
    logger.info("=" * 60)
    logger.info("  INSURANCE AGENT SCRAPER v2 — Autonomous Pipeline")
    logger.info(f"  Worker ID: {WORKER_ID}")
    logger.info(f"  NAIC SOLAR: {NAIC_SOLAR_URL}")
    logger.info(f"  States: {len(SBS_STATES)}")
    logger.info(f"  Prefixes per state: {TOTAL_PREFIXES:,}")
    logger.info(f"  Headless: {HEADLESS}")
    logger.info(f"  Proxy: {'Yes' if PROXY_URL else 'No'}")
    logger.info(f"  Running stale threshold: {RUNNING_STALE_MINUTES}m")
    logger.info(f"  Monthly reset enabled: {ENABLE_MONTHLY_RESET}")
    logger.info(f"  Inter-state sleep: {INTER_STATE_SLEEP}s")
    logger.info("=" * 60)

    # Initialize state queue
    StateQueue.initialize()

    states_completed = 0

    while True:
        state_run = StateQueue.claim_next_state(WORKER_ID)

        if not state_run:
            counts = StateQueue.queue_counts()
            logger.info(
                f"No pending states to claim. "
                f"pending={counts.get('pending', 0)} running={counts.get('running', 0)} completed={counts.get('completed', 0)}"
            )

            # Other workers are likely still active.
            if counts.get('running', 0) > 0:
                time.sleep(300)
                continue

            # Nothing running + nothing pending.
            if ENABLE_MONTHLY_RESET:
                logger.info("Resetting completed states for monthly re-scrape...")
                supabase.table("scrape_runs").update({
                    'status': 'pending',
                    'last_prefix': 'A',
                    'prefixes_completed': 0,
                    'total_found': 0,
                    'qualified': 0,
                    'saved': 0,
                    'errors': 0,
                    'started_at': None,
                    'completed_at': None,
                    'updated_at': datetime.now().isoformat()
                }).eq("status", "completed").execute()
                time.sleep(60)
            else:
                logger.info("All work complete. Sleeping 1 hour (monthly reset disabled).")
                time.sleep(3600)
            continue

        state_name = state_run['state']
        state_id = state_run['id']
        start_prefix = state_run.get('last_prefix', 'A') or 'A'

        logger.info(f"\n{'=' * 60}")
        logger.info(f"  SCRAPING: {state_name}")
        logger.info(f"  Resume from prefix: {start_prefix}")
        logger.info(f"{'=' * 60}")

        scraper = InsuranceAgentScraper(state_name, headless=HEADLESS)

        try:
            scraper.scrape_all(start_prefix=start_prefix, state_run_id=state_id)
            StateQueue.complete_state(state_id, scraper.stats)
            states_completed += 1
            logger.info(f"✅ {state_name} complete! ({states_completed} states done)")
        except KeyboardInterrupt:
            logger.info("\nStopped by user")
            StateQueue.update_progress(state_id, start_prefix, scraper.stats)
            scraper.close()
            sys.exit(0)
        except Exception as e:
            logger.error(f"❌ {state_name} failed: {e}")
            traceback.print_exc()
            StateQueue.fail_state(state_id, scraper.stats)
        finally:
            scraper.close()

        # Sleep between states to be polite to NAIC
        if INTER_STATE_SLEEP > 0:
            logger.info(f"Sleeping {INTER_STATE_SLEEP}s before next state...")
            time.sleep(INTER_STATE_SLEEP)


if __name__ == "__main__":
    main()
