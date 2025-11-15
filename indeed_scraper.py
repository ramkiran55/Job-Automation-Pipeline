"""
Indeed Job Scraper - Optimized with Concurrency
Uses the same Trie-based skill matching as LinkedIn scraper
"""

import asyncio
import json
import re
from datetime import datetime
from typing import List, Dict, Optional, Set
from playwright.async_api import async_playwright, Page, TimeoutError as PlaywrightTimeout


class TrieNode:
    """Node for Trie data structure"""
    def __init__(self):
        self.children = {}
        self.is_end_of_word = False
        self.skill = None


class SkillTrie:
    """Trie for efficient skill matching - O(m) where m is description length"""
    
    def __init__(self):
        self.root = TrieNode()
        
    def insert(self, skill: str):
        """Insert a skill into the Trie"""
        node = self.root
        for char in skill.lower():
            if char not in node.children:
                node.children[char] = TrieNode()
            node = node.children[char]
        node.is_end_of_word = True
        node.skill = skill
    
    def search_in_text(self, text: str) -> Set[str]:
        """Find all skills in text using Trie - single pass O(m)"""
        text = text.lower()
        found_skills = set()
        
        for i in range(len(text)):
            node = self.root
            j = i
            
            while j < len(text) and text[j] in node.children:
                node = node.children[text[j]]
                if node.is_end_of_word:
                    if self._is_word_boundary(text, i, j):
                        found_skills.add(node.skill)
                j += 1
        
        return found_skills
    
    def _is_word_boundary(self, text: str, start: int, end: int) -> bool:
        """Check if match is at word boundary"""
        if start > 0 and text[start - 1].isalnum():
            return False
        if end < len(text) - 1 and text[end + 1].isalnum():
            return False
        return True


class JobMatcher:
    """Optimized job matching with compiled patterns and hash sets"""
    
    MY_SKILLS = {
        'python', 'java', 'sql', 't-sql', 'pl/sql', 'plsql', 'shell', 'bash',
        'yaml', 'c#', 'c++', 'javascript', 'js', 'aws', 's3', 'glue', 'lambda',
        'step functions', 'redshift', 'ecs', 'fargate', 'ses', 'sns', 'eventbridge',
        'secrets manager', 'cloudwatch', 'rds', 'ec2', 'etl', 'elt', 'spark',
        'pyspark', 'airflow', 'kafka', 'ssis', 'ssrs', 'data pipeline',
        'data warehouse', 'glue studio', 'sql server', 'postgresql', 'postgres',
        'mysql', 'oracle', 'mongodb', 'dynamodb', 'nosql', 'terraform', 'docker',
        'kubernetes', 'k8s', 'ci/cd', 'github actions', 'git', 'jenkins',
        'spring boot', 'spring', 'hibernate', 'flask', 'rest api', 'restful',
        'pandas', 'sqlalchemy', 'fastapi', 'power bi', 'powerbi', 'tableau',
        'looker', 'quicksight', 'json', 'parquet', 'avro', 'csv', 'xml'
    }
    
    skill_trie = SkillTrie()
    for skill in MY_SKILLS:
        skill_trie.insert(skill)
    
    _visa_positive_pattern = re.compile(
        r'\b(visa sponsor|h1b sponsor|work authorization|visa support|sponsorship available|will sponsor)\b',
        re.IGNORECASE
    )
    _visa_negative_pattern = re.compile(
        r'\b(no sponsorship|cannot sponsor|no visa support|us citizen|citizenship required|must be authorized)\b',
        re.IGNORECASE
    )
    
    @classmethod
    def extract_skills(cls, text: str) -> List[str]:
        """Extract matching skills using Trie - O(m) time complexity"""
        return sorted(cls.skill_trie.search_in_text(text))
    
    @classmethod
    def calculate_match_score(cls, skills: List[str], description: str) -> float:
        """Calculate match score (0.0 to 1.0) based on skills and keywords"""
        if not skills:
            return 0.0
        
        score = 0.0
        description_lower = description.lower()
        
        skill_match_ratio = len(skills) / 20
        score += min(skill_match_ratio, 0.6)
        
        cloud_keywords = {'aws', 'cloud', 's3', 'lambda', 'glue', 'redshift'}
        cloud_matches = sum(1 for kw in cloud_keywords if kw in description_lower)
        score += min(cloud_matches / len(cloud_keywords), 0.15)
        
        senior_keywords = {'senior', 'lead', 'architect', 'principal'}
        if any(kw in description_lower for kw in senior_keywords):
            score += 0.10
        
        de_keywords = {'data engineer', 'etl', 'pipeline', 'warehouse', 'spark'}
        de_matches = sum(1 for kw in de_keywords if kw in description_lower)
        score += min(de_matches / len(de_keywords), 0.15)
        
        return min(score, 1.0)
    
    @classmethod
    def detect_visa_sponsorship(cls, text: str) -> Optional[bool]:
        """Detect visa sponsorship using compiled regex"""
        if cls._visa_negative_pattern.search(text):
            return False
        if cls._visa_positive_pattern.search(text):
            return True
        return None


class IndeedScraper:
    def __init__(self, role: str = "Data Engineer", location: str = "United States"):
        self.role = role
        self.location = location
        self.base_url = "https://www.indeed.com/jobs"
        self.jobs = []
        self.seen_job_ids = set()
        
    async def scrape(self, max_jobs: int = 25, concurrency: int = 3) -> List[Dict]:
        """Main scraping function with concurrent job fetching"""
        print(f"Starting Indeed scrape for: {self.role} in {self.location}")
        print(f"Target: {max_jobs} jobs | Concurrency: {concurrency} parallel requests\n")
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=['--disable-blink-features=AutomationControlled']
            )
            
            context = await browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            )
            
            try:
                page = await context.new_page()
                search_url = self._build_search_url()
                print(f"Navigating to: {search_url}\n")
                
                await page.goto(search_url, wait_until='domcontentloaded', timeout=30000)
                await asyncio.sleep(3)
                
                # Scroll to load more jobs
                await self._scroll_to_load_jobs(page)
                
                # Extract job cards - Indeed uses different selectors
                job_cards = await page.query_selector_all('div.job_seen_beacon')
                if not job_cards:
                    # Fallback selector
                    job_cards = await page.query_selector_all('div.cardOutline')
                
                print(f"Found {len(job_cards)} job cards")
                
                # Extract basic info from all cards
                job_list = []
                for idx, card in enumerate(job_cards[:max_jobs], 1):
                    job_data = await self._extract_job_card(card, idx)
                    if job_data and job_data.get('job_key'):
                        job_list.append(job_data)
                
                await page.close()
                
                # Concurrent processing
                print(f"\nFetching details for {len(job_list)} jobs (batches of {concurrency})...\n")
                
                for i in range(0, len(job_list), concurrency):
                    batch = job_list[i:i + concurrency]
                    print(f"Processing batch {i//concurrency + 1} (jobs {i+1}-{min(i+concurrency, len(job_list))})...")
                    
                    tasks = [
                        self._fetch_job_details(context, job_data, idx + i + 1)
                        for idx, job_data in enumerate(batch)
                    ]
                    
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    
                    for idx, result in enumerate(results):
                        if isinstance(result, Exception):
                            print(f"   [{i+idx+1}] WARNING Failed: {str(result)[:50]}")
                        elif result:
                            self.jobs.append(result)
                        else:
                            print(f"   [{i+idx+1}] WARNING No data returned")
                    
                    await asyncio.sleep(2)
                
            except Exception as e:
                print(f"ERROR Scraping error: {str(e)}")
            finally:
                await browser.close()
        
        self.jobs.sort(key=lambda x: x.get('match_score', 0), reverse=True)
        
        print(f"\nScraping complete! Extracted {len(self.jobs)} jobs")
        return self.jobs
    
    def _build_search_url(self) -> str:
        """Build Indeed job search URL"""
        # Indeed URL format: /jobs?q=Data+Engineer&l=United+States&fromage=7
        role_encoded = self.role.replace(' ', '+')
        location_encoded = self.location.replace(' ', '+')
        # fromage=7 means last 7 days
        url = f"{self.base_url}?q={role_encoded}&l={location_encoded}&fromage=7"
        return url
    
    async def _scroll_to_load_jobs(self, page: Page, scrolls: int = 3):
        """Scroll page to trigger lazy loading"""
        print("Scrolling to load more jobs...")
        for i in range(scrolls):
            await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
            await asyncio.sleep(2)
    
    async def _extract_job_card(self, card, idx: int) -> Optional[Dict]:
        """Extract basic data from a job card"""
        try:
            # Job title - Indeed uses h2 with specific class
            title_elem = await card.query_selector('h2.jobTitle span[title]')
            if not title_elem:
                title_elem = await card.query_selector('h2.jobTitle')
            job_title = (await title_elem.get_attribute('title')) if title_elem else None
            if not job_title and title_elem:
                job_title = (await title_elem.inner_text()).strip()
            
            # Company name
            company_elem = await card.query_selector('span[data-testid="company-name"]')
            if not company_elem:
                company_elem = await card.query_selector('span.companyName')
            company_name = (await company_elem.inner_text()).strip() if company_elem else "Unknown"
            
            # Location
            location_elem = await card.query_selector('div[data-testid="text-location"]')
            if not location_elem:
                location_elem = await card.query_selector('div.companyLocation')
            location = (await location_elem.inner_text()).strip() if location_elem else "Unknown"
            
            # Job key (Indeed's unique identifier)
            job_link_elem = await card.query_selector('a[data-jk]')
            if not job_link_elem:
                job_link_elem = await card.query_selector('a.jcs-JobTitle')
            
            job_key = None
            if job_link_elem:
                job_key = await job_link_elem.get_attribute('data-jk')
                if not job_key:
                    href = await job_link_elem.get_attribute('href')
                    if href:
                        match = re.search(r'jk=([a-f0-9]+)', href)
                        if match:
                            job_key = match.group(1)
            
            if not job_key:
                return None
            
            job_id = f"indeed_{job_key}"
            
            # Check for duplicates
            if job_id in self.seen_job_ids:
                return None
            self.seen_job_ids.add(job_id)
            
            # Posted date (relative)
            date_elem = await card.query_selector('span.date')
            posted_date = (await date_elem.inner_text()).strip() if date_elem else None
            
            return {
                'job_id': job_id,
                'job_key': job_key,
                'source': 'indeed',
                'job_title': job_title or "Unknown",
                'company_name': company_name,
                'location': location,
                'posted_date': posted_date,
                'scraped_at': datetime.utcnow().isoformat() + 'Z',
                'status': 'new'
            }
            
        except Exception as e:
            return None
    
    async def _fetch_job_details(self, context, job_data: Dict, idx: int) -> Optional[Dict]:
        """Fetch job details from job page"""
        page = None
        try:
            page = await context.new_page()
            
            # Build job URL
            job_url = f"https://www.indeed.com/viewjob?jk={job_data['job_key']}"
            job_data['application_link'] = job_url
            
            await page.goto(job_url, wait_until='domcontentloaded', timeout=15000)
            await asyncio.sleep(2)  # Increased wait time
            
            # DEBUG: Save screenshot and HTML
            if idx == 1:
                await page.screenshot(path='indeed_debug.png')
                html_content = await page.content()
                with open('indeed_debug.html', 'w', encoding='utf-8') as f:
                    f.write(html_content)
                print(f"   DEBUG: Saved screenshot and HTML for inspection")
            
            # Try multiple selectors for description
            desc_elem = None
            selectors = [
                '#jobDescriptionText',
                'div.jobsearch-jobDescriptionText',
                'div[id*="jobDescriptionText"]',
                'div.job-description',
                'div[class*="description"]'
            ]
            
            for selector in selectors:
                desc_elem = await page.query_selector(selector)
                if desc_elem:
                    print(f"   DEBUG: Found description with selector: {selector}")
                    break
            
            if desc_elem:
                job_data['job_description'] = (await desc_elem.inner_text()).strip()
                
                # Use optimized skill matching
                job_data['skills'] = JobMatcher.extract_skills(job_data['job_description'])
                job_data['match_score'] = JobMatcher.calculate_match_score(
                    job_data['skills'], 
                    job_data['job_description']
                )
                
                job_data['visa_sponsorship'] = JobMatcher.detect_visa_sponsorship(
                    job_data['job_description']
                )
                
                # Detect work mode
                desc_lower = job_data['job_description'].lower()
                if 'remote' in desc_lower or 'work from home' in desc_lower:
                    job_data['work_mode'] = 'remote'
                elif 'hybrid' in desc_lower:
                    job_data['work_mode'] = 'hybrid'
                else:
                    job_data['work_mode'] = 'onsite'
                
                print(f"   [{idx}] OK {job_data['job_title'][:50]} | Match: {job_data['match_score']:.0%} | Skills: {len(job_data['skills'])}")
                
                return job_data
            else:
                print(f"   [{idx}] WARNING No description found with any selector")
                return None
            
        except PlaywrightTimeout as e:
            print(f"   [{idx}] WARNING Timeout: {job_data['job_title'][:40]}")
            return None
        except Exception as e:
            print(f"   [{idx}] WARNING Error: {str(e)[:50]}")
            return None
        finally:
            if page:
                await page.close()
    
    def save_to_json(self, filename: str = None):
        """Save scraped jobs to JSON file"""
        if not filename:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"indeed_jobs_{timestamp}.json"
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(self.jobs, f, indent=2, ensure_ascii=False)
        
        print(f"Saved {len(self.jobs)} jobs to {filename}")
        return filename
    
    def filter_and_summarize(self, min_match_score: float = 0.5):
        """Filter jobs and print summary"""
        filtered = [j for j in self.jobs if j.get('match_score', 0) >= min_match_score]
        
        print("\n" + "="*80)
        print(f"JOB MATCHING SUMMARY (Min Match Score: {min_match_score:.0%})")
        print("="*80)
        print(f"Total jobs scraped: {len(self.jobs)}")
        print(f"High-quality matches (>={min_match_score:.0%}): {len(filtered)}")
        if self.jobs:
            print(f"Average match score: {sum(j.get('match_score', 0) for j in self.jobs) / len(self.jobs):.0%}")
        
        print(f"\nTOP 10 MATCHES:")
        print("-" * 80)
        for i, job in enumerate(filtered[:10], 1):
            score = job.get('match_score', 0)
            skills = len(job.get('skills', []))
            visa = "Yes" if job.get('visa_sponsorship') else "Unknown"
            work_mode = job.get('work_mode', 'Unknown')
            
            print(f"{i:2d}. [{score:.0%}] {job['job_title']}")
            print(f"    {job['company_name']} | {job['location']}")
            print(f"    Skills: {skills} | Work: {work_mode} | Visa: {visa}")
            print()
        
        print("="*80)


async def main():
    """Run the Indeed scraper"""
    scraper = IndeedScraper(
        role="Data Engineer",
        location="United States"
    )
    
    # Start with just 3 jobs to debug
    jobs = await scraper.scrape(max_jobs=3, concurrency=1)
    
    if jobs:
        scraper.save_to_json()
        scraper.filter_and_summarize(min_match_score=0.5)
    else:
        print("\nNo jobs were successfully scraped.")
        print("Check indeed_debug.png and indeed_debug.html files for details.")


if __name__ == "__main__":
    asyncio.run(main())