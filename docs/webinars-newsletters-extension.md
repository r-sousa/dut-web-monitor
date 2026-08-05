# Webinars and newsletters extension

## Webinars

`public/webinars.json` is a dedicated, enriched subset of DUT event pages whose titles identify the Urban Lunch Talks series. It preserves the event link and date and adds episode number, recording URL, speakers and moderator when exposed in the source HTML.

The webinar list is discovered from both the general events collection and the European series page. Legacy JPI Urban Europe episodes that are not exposed as DUT event pages are not silently manufactured; they may later be loaded as a separately governed seed dataset.

## Newsletters

`public/newsletters.json` reads the public archive links under **NEWSLETTERS** on the CCDR NORTE DUT documentation page. The European DUT page currently provides subscription but not a complete browsable archive, so the regional page is the authoritative public index used here.

Mailchimp recipient-tracking parameter `e` is removed before publication. Campaign identifiers needed to open the public archive are retained. `issue_sort_date` uses the first day of the displayed month, or a seasonal anchor, solely to support sorting; it is not claimed as the exact send date.
