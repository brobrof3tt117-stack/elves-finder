# Sealed Elves Finder: setup guide

This puts your Elves finder online as a free website that checks eBay by itself every hour. Once it is set up, anyone can open it on any phone or computer with a link. Nothing needs to stay running on your PC. This folder on your PC is your backup copy.

It takes about 30 minutes, plus waiting up to one business day for eBay to approve your developer account. Everything here is free.

## Already have an eBay developer account?

If you already made one for another project (like a deal scanner), you can skip the account signup and approval wait. Sign in at developer.ebay.com and go straight to Step 2.

**You can reuse the same keys.** eBay gives each keyset 5,000 searches per day and only gives one Production keyset per account. This site is built to be light: about 16 searches per update, roughly 400 per day. That leaves plenty of room for another tool on the same keys. If your other tool already uses close to 5,000 a day by itself, see "Fixing problems" below.

## Step 1: Make a free eBay developer account

1. Go to developer.ebay.com and click **Join** (top right).
2. Fill in the form. You can use your normal eBay login details or new ones.
3. Confirm your email. eBay may take up to one business day to approve the account. You will get an email when it is ready.

## Step 2: Get your two eBay keys

1. Sign in at developer.ebay.com, click your name (top right), then **Application Keysets**.
2. If you already have a Production keyset (from another project), use those same keys and skip to number 4. Otherwise, type a name like `ElvesFinder` and click **Create a keyset** under **Production** (not Sandbox).
3. eBay asks about "Marketplace account deletion notifications" (or shows "Your keyset is currently disabled"). Click the **exemption** link, turn on the **Not persisting eBay data** option, pick "I do not persist eBay data", and give the reason "Read-only listing search, no user data stored." That is true: this app never saves seller names or buyer info. Go back to Application Keysets and make sure the new keyset no longer says disabled.
4. You will now see your Production keys. You need two of them:
   - **App ID (Client ID)**
   - **Cert ID (Client Secret)**
5. Keep this page open. Treat the Cert ID like a password and never post it anywhere.

## Step 3: Make a GitHub account and a new repository

GitHub is the free service that will host the website and run the hourly check.

1. Go to github.com and sign up for a free account.
2. Click the **+** (top right), then **New repository**.
3. Repository name: `elves-finder`
4. Choose **Public** (required for the free website).
5. Tick **Add a README file**.
6. Click **Create repository**.

## Step 4: Add your eBay keys to GitHub (safely)

These stay private even though the repository is public.

1. In your repository, click **Settings** (top menu).
2. On the left, click **Secrets and variables**, then **Actions**.
3. Click **New repository secret**.
   - Name: `EBAY_CLIENT_ID`
   - Secret: paste your **App ID**
   - Click **Add secret**
4. Click **New repository secret** again.
   - Name: `EBAY_CLIENT_SECRET`
   - Secret: paste your **Cert ID**
   - Click **Add secret**

The names must be typed exactly as shown, in capital letters.

## Step 5: Turn on the website

1. Still in **Settings**, click **Pages** on the left.
2. Under **Build and deployment**, set **Source** to **GitHub Actions**.

That's all on this page. There is nothing to save.

## Step 6: Upload the files

1. Unzip `elves-sealed-finder.zip` on your PC.
2. Open the unzipped folder. You will see `site`, `updater`, and this guide. On Windows you may also see a folder named `.github`.
3. Go back to the main page of your repository (click `elves-finder` at the top).
4. Click **Add file**, then **Upload files**.
5. Select everything inside the unzipped folder (Ctrl+A on Windows, Cmd+A on Mac) and drag it onto the GitHub page.
6. Wait until all files finish uploading, then click **Commit changes**.

## Step 7: Add the hourly check file (only if needed)

Look at your repository's main page. If you see a folder named `.github`, skip this step.

If you do not see `.github` (Macs hide it), do this:

1. Click **Add file**, then **Create new file**.
2. In the name box, type exactly: `.github/workflows/update.yml`
   (GitHub turns each `/` into a folder as you type. That is normal.)
3. On your PC, open the file `update.yml` inside `.github/workflows` in the unzipped folder with Notepad or TextEdit. If you cannot see it, use the copy named `update.yml` inside the `updater` folder instead. They are identical.
4. Copy everything in it and paste it into the big box on GitHub.
5. Click **Commit changes**.

## Step 8: Watch it run, then open your site

1. Click the **Actions** tab. You will see "Update eBay listings" running (a yellow dot).
2. After about 3 to 5 minutes it turns into a green check.
3. Go to **Settings**, then **Pages**. At the top you will see "Your site is live at" followed by a link, like `https://yourname.github.io/elves-finder/`.
4. Open that link. Bookmark it and share it with anyone you like. It works on phones too.

From now on it updates itself about every hour. GitHub's timer can run a few minutes late when it is busy. That is normal.

## Changing the settings

All the filters live in one file: `updater/settings.json`.

1. In your repository, click `updater`, then `settings.json`.
2. Click the pencil icon (Edit).
3. Change a number, for example `"min_seller_positive_percent": 98`.
4. Click **Commit changes**. The site updates within a few minutes.

What you can change:

- `min_seller_positive_percent`: lowest seller feedback % allowed (now 95)
- `min_seller_ratings`: fewest seller ratings allowed (now 50)
- `show_buy_it_now`: show Buy It Now listings (now true)
- `show_auctions`: show auctions (now true)
- `us_sellers_only`: only sellers located in the US (now true)
- `hide_words`: titles with these words are hidden (opened, used, lot and more)
- `box_warning_words`: titles with these get a yellow box damage tag (damaged, crushed and more)

Keep the quote marks and commas exactly as they are when you edit. If the site stops updating after an edit, a missing comma is the usual cause.

## Updating right now instead of waiting

1. Click the **Actions** tab.
2. Click **Update eBay listings** on the left.
3. Click **Run workflow**, then the green **Run workflow** button.

## Fixing problems

- **Site says "the eBay keys are missing":** redo Step 4. Check the secret names are exactly `EBAY_CLIENT_ID` and `EBAY_CLIENT_SECRET`. Then run an update (see above).
- **Site says "eBay did not accept the keys":** you may have copied the Sandbox keys or an extra space. Copy the **Production** App ID and Cert ID again and update both secrets.
- **Red X in the Actions tab:** click it, then click the red step to read the message. If it says "Get Pages site failed", redo Step 5. If eBay was down, the next hourly run usually fixes itself and the site keeps showing the last good results.
- **Site says listings are more than 4 hours old:** go to the Actions tab. If you see a yellow banner saying workflows are disabled, click **Enable**.
- **Listings stop updating partway through the day while another tool shares the keys:** the two together hit eBay's 5,000 daily limit. Open `.github/workflows/update.yml`, change `"17 * * * *"` to `"17 */3 * * *"` (every 3 hours) and commit.
- **Your site link shows a 404 page:** wait 5 minutes after the first green check, then refresh.

## Good to know

- **Sealed is a best effort.** The finder only keeps listings eBay marks as "New" and hides titles that mention opened, used, incomplete, or bundled items. A dishonest seller can still mislabel a set, so always read the listing and photos before buying.
- **95% feedback is lenient.** Most solid eBay sellers are at 99% or higher. If you see bad sellers slipping through, raise it to 98.
- **The magazine gift packs** (Enki, Flamy, Miku, Jynx, Mr. Spry, Hidee) are rarely listed with their set number, so the finder matches them by name. They will show fewer results and occasionally an odd one.
- **Set pictures** are the official LEGO box photos from the LEGO Wiki on Fandom. The site looks each one up once and remembers it. The 6 magazine gift packs have no wiki picture, so they show an eBay photo instead (or their set number if nothing is for sale).
- **Keychains** are not included because LEGO files them as merchandise, not sets.
- **Costs:** eBay's API, GitHub, and the website are all free for this. The finder uses roughly 400 of eBay's 5,000 free searches per day.
