---
name: crawl-ethics
description: Legal and ethical guardrails for crawling and for building datasets from crawled content. Use whenever adding a spider, widening a crawl scope, changing rate limits or the user agent, or publishing a dataset built from scraped pages.
allowed-tools: Read, Edit, Write, Grep, Glob, Bash
---

# Crawl ethics and legal guardrails

This project turns other people's websites into datasets. That is legitimate
work with real constraints, and the constraints are cheap to honour and
expensive to ignore.

## Non-negotiable defaults

| Setting | Value | Why |
| :--- | :--- | :--- |
| `ROBOTSTXT_OBEY` | `True` | Never flip this to ship a crawl. If a site disallows you, that is the answer |
| `DOWNLOAD_DELAY` | 1s or higher | A crawl that degrades a site for its real users is an outage you caused |
| `AUTOTHROTTLE_ENABLED` | `True` | Adapts when the server slows down, which is it asking you to back off |
| `USER_AGENT` | Honest, with contact | An operator who wants you to stop must be able to reach you |
| `CONCURRENT_REQUESTS_PER_DOMAIN` | Low | Politeness is per-domain, not global |

The existing `immo_crawl/settings.py` has these set correctly. Do not weaken
them to make a crawl finish faster.

## Never do these

- **Impersonate a browser to evade bot detection.** A spoofed user agent whose
  purpose is to look human is circumvention, not configuration.
- **Bypass a paywall, login, CAPTCHA, or rate limit.**
- **Crawl personal data** (names, emails, addresses, profiles) without a lawful
  basis. GDPR applies to scraped personal data exactly as it does to collected
  data, and "it was public" is not a lawful basis.
- **Ignore a takedown or a `Crawl-delay`.**
- **Republish scraped content wholesale.** Copyright survives scraping.

If asked to do one of these, say plainly which one and why it is refused, then
offer the legitimate path: an API, a data licence, a partnership, or a smaller
scope.

## Before adding a spider

1. Read the site's `robots.txt` and terms of service.
2. Check for an API or bulk download. It is nearly always cheaper than scraping
   and it is explicitly permitted.
3. Scope to what you need. "Crawl the whole site" is rarely the requirement.
4. Set a contact address in the user agent.
5. Record the legal basis and date in the spider's docstring.

## Before publishing a dataset

- Strip personal data. `webcorpus` does **not** do PII removal; there is no
  such stage, and assuming otherwise is a compliance incident.
- Keep source URLs so provenance is auditable and takedowns are actionable.
- State the licence, the crawl date, and the collection method.
- Provide a removal path for anyone who asks.

## What this project does not do

Do not claim otherwise in docs or code comments:

- No PII detection or redaction.
- No licence detection.
- No robots.txt enforcement inside `webcorpus` itself; that belongs to the
  crawler upstream.
- No copyright or terms of service checking.

`webcorpus` filters for corpus *quality*, not for legal *permissibility*. They
are different problems and only one of them is solved here.
