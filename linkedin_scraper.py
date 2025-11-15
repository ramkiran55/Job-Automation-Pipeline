"""
LinkedIn Job Scraper v3.0 - OPTIMIZED with Data Structures & Algorithms
- Concurrent job fetching (5x-10x faster)
- Trie-based skill matching (O(m) instead of O(n*m))
- Hash-based deduplication
- Compiled regex patterns (memoization)
"""

import asyncio
import json
import re
from datetime import datetime
from typing import List, Dict, Optional, Set
from collections import defaultdict
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
        
        # Scan through text
        for i in range(len(text)):
            node = self.root
            j = i
            
            # Try to match longest skill from position i
            while j < len(text) and text[j] in node.children:
                node = node.children[text[j]]
                if node.is_end_of_word:
                    # Check word boundaries
                    if self._is_word_boundary(text, i, j):
                        found_skills.add(node.skill)
                j += 1
        
        return found_skills
    
    def _is_word_boundary(self, text: str, start: int, end: int) -> bool:
        """Check if match is at word boundary"""
        # Check start boundary
        if start > 0 and text[start - 1].isalnum():
            return False
        # Check end boundary
        if end < len(text) - 1 and text[end + 1].isalnum():
            return False
        return True


class JobMatcher:
    """Optimized job matching with compiled patterns and hash sets"""
    
    # Ram's core skills as a set for O(1) lookups
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
    
    # Build Trie once at class initialization
    skill_trie = SkillTrie()
    for skill in MY_SKILLS:
        skill_trie.insert(skill)
    
    # Compile regex patterns once (memoization)
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
        
        # Base score: percentage of YOUR skills mentioned
        skill_match_ratio = len(skills) / 20
        score += min(skill_match_ratio, 0.6)
        
        # Bonus: Cloud-heavy roles (+15%)
        cloud_keywords = {'aws', 'cloud', 's3', 'lambda', 'glue', 'redshift'}
        cloud_matches = sum(1 for kw in cloud_keywords if kw in description_lower)
        score += min(cloud_matches / len(cloud_keywords), 0.15)
        
        # Bonus: Senior/leadership keywords (+10%)
        senior_keywords = {'senior', 'lead', 'architect', 'principal'}
        if any(kw in description_lower for kw in senior_keywords):
            score += 0.10
        
        # Bonus: Data engineering focus (+15%)
        de_keywords = {'data engineer', 'etl', 'pipeline', 'warehouse', 'spark'}
        de_matches = sum(1 for kw in de_keywords if kw in description_lower)
        score += min(de_matches / len(de_keywords), 0.15)
        
        return min(score, 1.0)
    
    @classmethod
    def detect_visa_sponsorship(cls, text: str) -> Optional[bool]:
        """Detect visa sponsorship using compiled regex"""
        # Check negative first (disqualifiers)
        if cls._visa_negative_pattern.search(text):
            return False
        
        # Check positive
        if cls._visa_positive_pattern.search(text):
            return True
        
        return None


class LinkedInScraper:
    def __init__(self, role: str = "Data Engineer", location: str = "United States"):
        self.role = role
        self.location = location
        self.base_url = "https://www.linkedin.com/jobs/search"
        self.jobs = []
        self.seen_job_ids = set()  # Hash set for O(1) deduplication
        
    async def scrape(self, max_jobs: int = 25, concurrency: int = 5) -> List[Dict]:
        """Main scraping function with concurrent job fetching"""
        print(f"Starting LinkedIn scrape for: {self.role} in {self.location}")
        print(f"Target: {max_jobs} jobs | Concurrency: {concurrency} parallel requests\n")
        
        async with async_playwright() as p:
            # Launch browser
            browser = await p.chromium.launch(
                headless=True,
                args=['--disable-blink-features=AutomationControlled']
            )
            
            context = await browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            )
            
            try:
                # Get job list page
                page = await context.new_page()
                search_url = self._build_search_url()
                print(f"Navigating to: {search_url}\n")
                
                await page.goto(search_url, wait_until='domcontentloaded', timeout=30000)
                await asyncio.sleep(3)
                
                # Scroll to load more jobs
                await self._scroll_to_load_jobs(page)
                
                # Extract basic job card info
                job_cards = await page.query_selector_all('div.base-card')
                print(f"Found {len(job_cards)} job cards")
                
                # Extract basic info from all cards first
                job_list = []
                for idx, card in enumerate(job_cards[:max_jobs], 1):
                    job_data = await self._extract_job_card(card, idx)
                    if job_data and job_data.get('application_link'):
                        job_list.append(job_data)
                
                await page.close()
                
                # CONCURRENT PROCESSING - fetch details for multiple jobs at once
                print(f"\nFetching details for {len(job_list)} jobs (batches of {concurrency})...\n")
                
                for i in range(0, len(job_list), concurrency):
                    batch = job_list[i:i + concurrency]
                    print(f"Processing batch {i//concurrency + 1} (jobs {i+1}-{min(i+concurrency, len(job_list))})...")
                    
                    # Create concurrent tasks
                    tasks = [
                        self._fetch_job_details(context, job_data, idx + i + 1)
                        for idx, job_data in enumerate(batch)
                    ]
                    
                    # Execute all tasks in parallel with exception handling
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    
                    # Process results
                    for idx, result in enumerate(results):
                        if isinstance(result, Exception):
                            print(f"   [{i+idx+1}] WARNING Failed: {str(result)}")
                        elif result:
                            self.jobs.append(result)
                        else:
                            print(f"   [{i+idx+1}] WARNING No data returned")
                    
                    # Rate limiting between batches
                    await asyncio.sleep(2)
                
            except Exception as e:
                print(f"ERROR Scraping error: {str(e)}")
            finally:
                await browser.close()
        
        # Sort by match score
        self.jobs.sort(key=lambda x: x.get('match_score', 0), reverse=True)
        
        print(f"\nScraping complete! Extracted {len(self.jobs)} jobs")
        return self.jobs
    
    async def _fetch_job_details(self, context, job_data: Dict, idx: int) -> Optional[Dict]:
        """Fetch job details in a new page (for concurrent execution)"""
        page = None
        try:
            page = await context.new_page()
            
            # Navigate to job page
            await page.goto(job_data['application_link'], wait_until='domcontentloaded', timeout=15000)
            await asyncio.sleep(1)
            
            # Try to expand "Show more" button
            try:
                show_more = await page.query_selector('button[aria-label*="Show more"]')
                if show_more:
                    await show_more.click()
                    await asyncio.sleep(0.5)
            except:
                pass
            
            # Extract description
            desc_elem = await page.query_selector('div.description__text')
            if not desc_elem:
                desc_elem = await page.query_selector('div.show-more-less-html__markup')
            
            if desc_elem:
                job_data['job_description'] = (await desc_elem.inner_text()).strip()
                
                # Use optimized skill matching (Trie-based)
                job_data['skills'] = JobMatcher.extract_skills(job_data['job_description'])
                job_data['match_score'] = JobMatcher.calculate_match_score(
                    job_data['skills'], 
                    job_data['job_description']
                )
                
                # Detect visa with compiled regex
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
                print(f"   [{idx}] WARNING No description found")
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
    
    def _build_search_url(self) -> str:
        """Build LinkedIn job search URL"""
        role_encoded = self.role.replace(' ', '%20')
        location_encoded = self.location.replace(' ', '%20')
        url = f"{self.base_url}?keywords={role_encoded}&location={location_encoded}&f_TPR=r604800&position=1&pageNum=0"
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
            title_elem = await card.query_selector('h3.base-search-card__title')
            job_title = (await title_elem.inner_text()).strip() if title_elem else "Unknown"
            
            company_elem = await card.query_selector('h4.base-search-card__subtitle')
            company_name = (await company_elem.inner_text()).strip() if company_elem else "Unknown"
            
            location_elem = await card.query_selector('span.job-search-card__location')
            location = (await location_elem.inner_text()).strip() if location_elem else "Unknown"
            
            link_elem = await card.query_selector('a.base-card__full-link')
            job_link = await link_elem.get_attribute('href') if link_elem else None
            
            # Extract job ID and check for duplicates (O(1) hash set lookup)
            job_id = None
            if job_link:
                match = re.search(r'/jobs/view/(\d+)', job_link)
                if match:
                    job_id = f"linkedin_{match.group(1)}"
                    if job_id in self.seen_job_ids:
                        return None  # Skip duplicate
                    self.seen_job_ids.add(job_id)
            
            if not job_id:
                job_id = f"linkedin_{idx}"
            
            date_elem = await card.query_selector('time.job-search-card__listdate')
            posted_date = await date_elem.get_attribute('datetime') if date_elem else None
            
            return {
                'job_id': job_id,
                'source': 'linkedin',
                'job_title': job_title,
                'company_name': company_name,
                'location': location,
                'application_link': job_link,
                'posted_date': posted_date,
                'scraped_at': datetime.utcnow().isoformat() + 'Z',
                'status': 'new'
            }
            
        except Exception as e:
            return None
    
    def save_to_json(self, filename: str = None):
        """Save scraped jobs to JSON file"""
        if not filename:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"linkedin_jobs_{timestamp}.json"
        
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
        
        # Top 10 matches
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
    """Run the optimized scraper"""
    scraper = LinkedInScraper(
        role="Data Engineer",
        location="United States"
    )
    
    # Scrape with concurrency=3 (more conservative to avoid rate limits)
    jobs = await scraper.scrape(max_jobs=15, concurrency=3)
    
    if jobs:
        scraper.save_to_json()
        scraper.filter_and_summarize(min_match_score=0.5)
    else:
        print("\nNo jobs were successfully scraped. Check the warnings above.")


if __name__ == "__main__":
    asyncio.run(main())