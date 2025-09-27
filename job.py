import logging
import sqlite3
import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ParseMode
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters, CallbackContext

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Database setup
def init_db():
    conn = sqlite3.connect('jobs.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS jobs
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  title TEXT,
                  company TEXT,
                  location TEXT,
                  description TEXT,
                  url TEXT,
                  source TEXT,
                  user_id INTEGER,
                  saved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()

# Job scrapers
def scrape_indeed(query):
    """Scrape job postings from Indeed"""
    url = f"https://www.indeed.com/jobs?q={query}&l=Remote"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    response = requests.get(url, headers=headers)
    soup = BeautifulSoup(response.text, 'html.parser')
    
    jobs = []
    for card in soup.select('.job_seen_beacon'):
        try:
            title = card.select_one('h2.jobTitle').text.strip()
            company = card.select_one('.companyName').text.strip()
            location = card.select_one('.companyLocation').text.strip()
            snippet = card.select_one('.job-snippet').text.strip()
            link = "https://www.indeed.com" + card.select_one('h2.jobTitle a')['href']
            
            jobs.append({
                'title': title,
                'company': company,
                'location': location,
                'description': snippet,
                'url': link,
                'source': 'Indeed'
            })
        except Exception as e:
            logger.error(f"Error parsing Indeed job: {e}")
    
    return jobs[:5]  # Return top 5 results

def scrape_glassdoor(query):
    """Scrape job postings from Glassdoor"""
    url = f"https://www.glassdoor.com/Job/{query}-jobs-SRCH_IL.0,6_IS{query}_KO7,7.htm"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    response = requests.get(url, headers=headers)
    soup = BeautifulSoup(response.text, 'html.parser')
    
    jobs = []
    for card in soup.select('.react-job-listing'):
        try:
            title = card.select_one('.jobLink').text.strip()
            company = card.select_one('.jobHeader .jobEmpName').text.strip()
            location = card.select_one('.loc').text.strip()
            description = card.select_one('.jobDescription').text.strip()
            link = "https://www.glassdoor.com" + card.select_one('.jobLink')['href']
            
            jobs.append({
                'title': title,
                'company': company,
                'location': location,
                'description': description,
                'url': link,
                'source': 'Glassdoor'
            })
        except Exception as e:
            logger.error(f"Error parsing Glassdoor job: {e}")
    
    return jobs[:5]  # Return top 5 results

def scrape_remoteok(query):
    """Scrape job postings from RemoteOK"""
    url = "https://remoteok.io/remote-dev-jobs"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    response = requests.get(url, headers=headers)
    soup = BeautifulSoup(response.text, 'html.parser')
    
    jobs = []
    for card in soup.select('tr.job'):
        try:
            if not card.has_attr('data-company'):
                continue
                
            title = card.select_one('h2 a').text.strip()
            company = card['data-company']
            location = "Remote"
            description = card.select_one('.description').text.strip()
            link = "https://remoteok.io" + card.select_one('h2 a')['href']
            
            # Filter by query if provided
            if query.lower() not in title.lower() and query.lower() not in description.lower():
                continue
                
            jobs.append({
                'title': title,
                'company': company,
                'location': location,
                'description': description,
                'url': link,
                'source': 'RemoteOK'
            })
        except Exception as e:
            logger.error(f"Error parsing RemoteOK job: {e}")
    
    return jobs[:5]  # Return top 5 results

def scrape_linkedin(query):
    """Scrape job postings from LinkedIn (public jobs)"""
    url = f"https://www.linkedin.com/jobs/search/?keywords={query}&location=Remote"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    response = requests.get(url, headers=headers)
    soup = BeautifulSoup(response.text, 'html.parser')
    
    jobs = []
    for card in soup.select('.job-search-card'):
        try:
            title = card.select_one('h3.base-search-card__title').text.strip()
            company = card.select_one('h4.base-search-card__subtitle a').text.strip()
            location = card.select_one('.job-search-card__location').text.strip()
            link = card.select_one('a.base-card__full-link')['href']
            
            # Get description snippet
            description = "No description available"
            if card.select_one('.job-search-card__snippet'):
                description = card.select_one('.job-search-card__snippet').text.strip()
            
            jobs.append({
                'title': title,
                'company': company,
                'location': location,
                'description': description,
                'url': link,
                'source': 'LinkedIn'
            })
        except Exception as e:
            logger.error(f"Error parsing LinkedIn job: {e}")
    
    return jobs[:5]  # Return top 5 results

# Database functions
def save_job_to_db(user_id, job):
    """Save a job to the database"""
    conn = sqlite3.connect('jobs.db')
    c = conn.cursor()
    c.execute('''INSERT INTO jobs (title, company, location, description, url, source, user_id)
                 VALUES (?, ?, ?, ?, ?, ?, ?)''',
              (job['title'], job['company'], job['location'], 
               job['description'], job['url'], job['source'], user_id))
    conn.commit()
    conn.close()

def get_saved_jobs(user_id):
    """Get saved jobs for a user"""
    conn = sqlite3.connect('jobs.db')
    c = conn.cursor()
    c.execute('''SELECT id, title, company, location, source, url FROM jobs 
                 WHERE user_id = ? ORDER BY saved_at DESC LIMIT 10''', (user_id,))
    jobs = c.fetchall()
    conn.close()
    return jobs

# Bot handlers
def start(update: Update, context: CallbackContext):
    """Send a message when the command /start is issued."""
    keyboard = [
        [InlineKeyboardButton("🔍 Search Jobs", callback_data='search')],
        [InlineKeyboardButton("⭐ Saved Jobs", callback_data='saved')],
        [InlineKeyboardButton("ℹ️ Help", callback_data='help')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    update.message.reply_text(
        "🤖 Welcome to Job Aggregator Bot!\n\n"
        "I aggregate job postings from multiple job websites including:\n"
        "• Indeed\n"
        "• Glassdoor\n"
        "• LinkedIn\n"
        "• RemoteOK\n\n"
        "Use the buttons below to get started:",
        reply_markup=reply_markup
    )

def help_command(update: Update, context: CallbackContext):
    """Send a message when the command /help is issued."""
    update.message.reply_text(
        "🔍 *Job Search Bot Help*\n\n"
        "• /start - Show main menu\n"
        "• /search <query> - Search for jobs (e.g. /search python developer)\n"
        "• /saved - Show your saved jobs\n"
        "• /help - Show this help message\n\n"
        "You can also use the inline buttons in the main menu.",
        parse_mode=ParseMode.MARKDOWN
    )

def search_jobs(update: Update, context: CallbackContext):
    """Search for jobs based on user query"""
    if not context.args:
        update.message.reply_text(
            "Please provide a search term. Usage: /search <query>\n"
            "Example: /search python developer"
        )
        return
    
    query = ' '.join(context.args)
    update.message.reply_text(f"🔍 Searching for '{query}' jobs...")
    
    # Aggregate jobs from all sources
    all_jobs = []
    
    # Scrape Indeed
    try:
        indeed_jobs = scrape_indeed(query)
        all_jobs.extend(indeed_jobs)
    except Exception as e:
        logger.error(f"Indeed scraping failed: {e}")
    
    # Scrape Glassdoor
    try:
        glassdoor_jobs = scrape_glassdoor(query)
        all_jobs.extend(glassdoor_jobs)
    except Exception as e:
        logger.error(f"Glassdoor scraping failed: {e}")
    
    # Scrape RemoteOK
    try:
        remoteok_jobs = scrape_remoteok(query)
        all_jobs.extend(remoteok_jobs)
    except Exception as e:
        logger.error(f"RemoteOK scraping failed: {e}")
    
    # Scrape LinkedIn
    try:
        linkedin_jobs = scrape_linkedin(query)
        all_jobs.extend(linkedin_jobs)
    except Exception as e:
        logger.error(f"LinkedIn scraping failed: {e}")
    
    if not all_jobs:
        update.message.reply_text("No jobs found. Try different keywords.")
        return
    
    # Display results
    for i, job in enumerate(all_jobs[:5]):  # Show top 5 results
        keyboard = [
            [InlineKeyboardButton("💾 Save Job", callback_data=f'save_{i}')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Truncate description if too long
        description = job['description'][:200] + "..." if len(job['description']) > 200 else job['description']
        
        message = (
            f"*{job['title']}* at {job['company']}\n"
            f"📍 {job['location']} | 🏢 {job['source']}\n\n"
            f"{description}\n\n"
            f"[Apply Here]({job['url']})"
        )
        
        update.message.reply_text(
            message,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    
    # Store jobs in context for saving
    context.user_data['search_results'] = all_jobs[:5]

def saved_jobs(update: Update, context: CallbackContext):
    """Show saved jobs for the user"""
    user_id = update.effective_user.id
    jobs = get_saved_jobs(user_id)
    
    if not jobs:
        update.message.reply_text("You haven't saved any jobs yet.")
        return
    
    for job in jobs:
        job_id, title, company, location, source, url = job
        message = (
            f"*{title}* at {company}\n"
            f"📍 {location} | 🏢 {source}\n\n"
            f"[View Job]({url})"
        )
        
        keyboard = [
            [InlineKeyboardButton("🗑️ Remove", callback_data=f'remove_{job_id}')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        update.message.reply_text(
            message,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )

def button_callback(update: Update, context: CallbackContext):
    """Handle button callbacks"""
    query = update.callback_query
    query.answer()
    
    data = query.data
    
    if data == 'search':
        query.edit_message_text(
            "🔍 *Job Search*\n\n"
            "Please send me your job search query.\n"
            "Example: `python developer`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    if data == 'saved':
        saved_jobs(update, context)
        return
    
    if data == 'help':
        help_command(update, context)
        return
    
    if data.startswith('save_'):
        job_index = int(data.split('_')[1])
        jobs = context.user_data.get('search_results', [])
        
        if job_index < len(jobs):
            job = jobs[job_index]
            save_job_to_db(query.from_user.id, job)
            query.edit_message_text("✅ Job saved to your favorites!")
        else:
            query.edit_message_text("❌ Error: Job not found.")
        return
    
    if data.startswith('remove_'):
        job_id = int(data.split('_')[1])
        conn = sqlite3.connect('jobs.db')
        c = conn.cursor()
        c.execute("DELETE FROM jobs WHERE id = ? AND user_id = ?", (job_id, query.from_user.id))
        conn.commit()
        conn.close()
        
        query.edit_message_text("🗑️ Job removed from your saved list.")
        return

def handle_message(update: Update, context: CallbackContext):
    """Handle regular messages for job search"""
    text = update.message.text
    context.args = text.split()
    search_jobs(update, context)

def main():
    """Start the bot."""
    # Initialize database
    init_db()
    
    # Create the Updater and pass it your bot's token.
    updater = Updater("YOUR_TELEGRAM_BOT_TOKEN")

    # Get the dispatcher to register handlers
    dispatcher = updater.dispatcher

    # Register command handlers
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("help", help_command))
    dispatcher.add_handler(CommandHandler("search", search_jobs))
    dispatcher.add_handler(CommandHandler("saved", saved_jobs))
    
    # Register callback handler for inline buttons
    dispatcher.add_handler(CallbackQueryHandler(button_callback))
    
    # Register message handler for job search
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))

    # Start the Bot
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()