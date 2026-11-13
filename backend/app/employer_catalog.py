"""Example public job boards, in alphabetical order.

The list is a starting point, not an endorsement. Company names are trademarks of their
owners; NextUp is not affiliated with any of them. A board can disappear or change at any
time, and nothing here says that it is currently reachable.
"""

MAX_BOARDS = 40

# Each entry names a board on a provider's public job-board API.
CATALOG = [
    {
        "provider": provider,
        "board": board,
        "company": company,
        "sector": sector,
        "careers_url": (
            f"https://jobs.lever.co/{board}"
            if provider == "lever"
            else f"https://job-boards.greenhouse.io/{board}"
        ),
    }
    for provider, board, company, sector in (
        ("greenhouse", "affirm", "Affirm", "Fintech"),
        ("greenhouse", "airbnb", "Airbnb", "Travel"),
        ("greenhouse", "anthropic", "Anthropic", "AI research"),
        ("greenhouse", "asana", "Asana", "Productivity software"),
        ("greenhouse", "astranis", "Astranis", "Aerospace"),
        ("greenhouse", "betterment", "Betterment", "Fintech"),
        ("greenhouse", "chime", "Chime", "Fintech"),
        ("greenhouse", "cloudflare", "Cloudflare", "Infrastructure and security"),
        ("greenhouse", "coinbase", "Coinbase", "Fintech"),
        ("greenhouse", "coursera", "Coursera", "Education"),
        ("greenhouse", "databricks", "Databricks", "Data and AI platforms"),
        ("greenhouse", "datadog", "Datadog", "Cloud and observability"),
        ("greenhouse", "discord", "Discord", "Communications and gaming"),
        ("greenhouse", "doordashusa", "DoorDash", "Delivery and logistics"),
        ("greenhouse", "dropbox", "Dropbox", "Productivity software"),
        ("greenhouse", "duolingo", "Duolingo", "Education"),
        ("greenhouse", "esri", "Esri", "Geospatial software"),
        ("greenhouse", "figma", "Figma", "Design software"),
        ("greenhouse", "formlabs", "Formlabs", "Manufacturing and 3D printing"),
        ("greenhouse", "gitlab", "GitLab", "Developer tools"),
        ("greenhouse", "gusto", "Gusto", "Payroll and business software"),
        ("lever", "includedhealth", "Included Health", "Healthcare"),
        ("greenhouse", "instacart", "Instacart", "Retail and grocery"),
        ("greenhouse", "mongodb", "MongoDB", "Database software"),
        ("greenhouse", "okta", "Okta", "Identity and security"),
        ("greenhouse", "oscar", "Oscar Health", "Healthcare"),
        ("greenhouse", "peloton", "Peloton", "Fitness"),
        ("greenhouse", "pinterest", "Pinterest", "Media and discovery"),
        ("greenhouse", "reddit", "Reddit", "Media and communities"),
        ("greenhouse", "ripple", "Ripple", "Fintech"),
        ("lever", "ro", "Ro", "Healthcare"),
        ("greenhouse", "robinhood", "Robinhood", "Fintech"),
        ("greenhouse", "roblox", "Roblox", "Gaming"),
        ("greenhouse", "samsara", "Samsara", "Industrial software"),
        ("greenhouse", "sofi", "SoFi", "Fintech"),
        ("greenhouse", "toast", "Toast", "Retail and payments"),
        ("greenhouse", "twilio", "Twilio", "Communications software"),
        ("greenhouse", "upstart", "Upstart", "Fintech"),
        ("lever", "wealthfront", "Wealthfront", "Fintech"),
        ("greenhouse", "flyzipline", "Zipline", "Robotics and logistics"),
    )
]
