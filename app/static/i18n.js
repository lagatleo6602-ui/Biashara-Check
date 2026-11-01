/* Kiswahili for Biashara Check.
   The pages are written in English. When Kiswahili is chosen, this file swaps the text on the page
   (and text added later by the app) for its Kiswahili version, and can switch back without a reload.
   Anything not in the list below stays in English. The risk reasons come from the server already
   in the owner's language. */
(() => {
  const KEY = "bc-lang";
  const read = () => { try { return localStorage.getItem(KEY) === "sw" ? "sw" : "en"; } catch { return "en"; } };
  const write = v => { try { localStorage.setItem(KEY, v); } catch { /* private mode */ } };

  const SW = {
    // subscription and getting the app
    "Get the app": "Pata programu", "App": "Programu", "Pro is active until": "Pro inafanya kazi hadi",
    "Renew automatically when this plan ends": "Lipia upya kiotomatiki mpango huu ukiisha",
    "Cancel automatic renewal": "Sitisha kulipia upya kiotomatiki", "Keep renewing": "Endelea kulipia upya",
    "Yes, cancel renewal": "Ndiyo, sitisha", "Turn renewal back on": "Washa tena kulipia upya",
    "Your plan includes:": "Mpango wako unajumuisha:", "Install Biashara Check": "Sakinisha Biashara Check",
    "Get Biashara Check on your phone": "Weka Biashara Check kwenye simu yako", "How to install": "Jinsi ya kusakinisha",
    "Android phone": "Simu ya Android", "iPhone or iPad": "iPhone au iPad", "Computer": "Kompyuta", "Good to know": "Ni vizuri kujua",
    "Get the app on your phone": "Pata programu kwenye simu yako", "📱 Get the app on your phone": "📱 Pata programu kwenye simu yako",
    "Install the app": "Sakinisha programu", "Biashara Check on your phone": "Biashara Check kwenye simu yako",
    "Free · opens like an app · no Play Store": "Bure · inafunguka kama programu · bila Play Store", "How it works": "Jinsi inavyofanya kazi",
    "Biashara Check, right on your phone": "Biashara Check, moja kwa moja kwenye simu yako",
    "Free · No Play Store needed · Under 1 MB": "Bure · Bila Play Store · Chini ya MB 1",
    "Its own icon, opens full screen": "Ikoni yake, inafunguka skrini nzima", "Updates itself, nothing to download again": "Inajisasisha, hakuna cha kupakua tena",
    "Your figures stay safe on the server, not the phone": "Takwimu zako ziko salama kwenye seva, si kwenye simu",
    "Two taps to install": "Mibofyo miwili kusakinisha", "Got it": "Nimeelewa", "Free, installs in seconds, no Play Store": "Bure, inasakinishwa kwa sekunde, bila Play Store",
    "Show the Ask button": "Onyesha kitufe cha Uliza", "tuck it away": "kifiche pembeni",
    "The next 12 months, month by month": "Miezi 12 ijayo, mwezi kwa mwezi",
    "Chance of at least one loss month by each month. Tap a month to look that far ahead.": "Uwezekano wa angalau mwezi mmoja wa hasara kufikia kila mwezi. Gusa mwezi kuangalia hadi hapo.",
    "Your outlook": "Mwelekeo wako", "Look ahead": "Angalia mbele", "Chance of a loss month by each month": "Uwezekano wa mwezi wa hasara kufikia kila mwezi",
    "Choose how far ahead to look, from 1 to 12 months. We show the chance of at least one loss month in that time.":
      "Chagua umbali wa kuangalia mbele, miezi 1 hadi 12. Tunaonyesha uwezekano wa angalau mwezi mmoja wa hasara katika muda huo.",
    "What pushes it up": "Kinachoiongeza", "What keeps it down": "Kinachoipunguza", "How the outlook works": "Jinsi mwelekeo unavyofanya kazi",
    "1-12 months ahead": "Miezi 1-12 mbele",
    // assistant
    "Ask": "Uliza", "Ask Biashara Check": "Uliza Biashara Check", "Send": "Tuma",
    "Built-in helper: free, and your figures stay in the app": "Msaidizi wa ndani: bure, na takwimu zako zinabaki ndani ya programu",
    "Ask about your business…": "Uliza kuhusu biashara yako…", "Your question": "Swali lako", "Typing": "Inaandika",
    "Why is my risk at this level?": "Kwa nini hatari yangu iko hivi?", "What was my gross profit last month?": "Faida ghafi yangu mwezi uliopita?",
    "What if I cut running costs by 10%?": "Kama nikipunguza gharama za uendeshaji kwa 10%?", "How can I improve my profit?": "Nifanye nini kuongeza faida?",
    "Hello! I can answer questions about your sales, profit, cash and risk, explain any figure, try a what-if, or show you how to do something in the app.":
      "Habari! Ninaweza kujibu maswali kuhusu mauzo, faida, pesa na hatari yako, kueleza takwimu yoyote, kujaribu \"kama nikifanya\", au kukuonyesha jinsi ya kufanya kitu kwenye programu.",
    "Sorry, something went wrong. Please try again.": "Samahani, kuna tatizo. Tafadhali jaribu tena.",
    "You seem to be offline. Try again when you're connected.": "Inaonekana huna mtandao. Jaribu tena ukiunganishwa.",
    // method page, figures, distress check, username
    "How it's calculated": "Jinsi inavyokokotolewa", "Method": "Mbinu", "Tour": "Ziara",
    "Username and password": "Jina la mtumiaji na nenosiri", "Username": "Jina la mtumiaji",
    "New username": "Jina jipya la mtumiaji", "Change username": "Badilisha jina la mtumiaji",
    "Current password": "Nenosiri la sasa", "Username, business code or email": "Jina la mtumiaji, msimbo wa biashara au barua pepe",
    "Gross profit": "Faida ghafi", "Cash left over": "Pesa iliyobaki",
    "Your business figures": "Takwimu za biashara yako", "How they're calculated": "Jinsi zinavyokokotolewa",
    "Every figure, with its formula": "Kila takwimu, pamoja na kanuni yake",
    "Tap a figure to see how it's worked out with your own numbers.": "Gusa takwimu uone inavyokokotolewa kwa namba zako.",
    "Profit and loss": "Faida na hasara", "Cash flow": "Mtiririko wa pesa", "Total sales": "Mauzo yote",
    "Cost of goods sold": "Gharama ya bidhaa zilizouzwa", "Running expenses": "Gharama za uendeshaji",
    "Operating profit": "Faida ya uendeshaji", "Money received": "Pesa zilizopokelewa", "Money paid out": "Pesa zilizolipwa",
    "Net cash flow": "Mtiririko halisi wa pesa", "minus ": "toa ",
    "Warnings from business rules": "Tahadhari kutoka kwa kanuni za biashara",
    "Formula": "Kanuni", "With your numbers": "Kwa namba zako", "What it means": "Maana yake",
    "OK": "Sawa", "Watch": "Angalia", "Problem": "Tatizo",
    "Financial distress check": "Ukaguzi wa dhiki ya kifedha", "Pushing the chance up": "Yanayoongeza uwezekano",
    "Keeping it down": "Yanayopunguza uwezekano", "See the full calculation": "Ona hesabu kamili",
    "How this model works and how well it tested": "Jinsi modeli hii inavyofanya kazi na ilivyofanya katika majaribio",
    "How the % is worked out, and how accurate it is": "Jinsi asilimia inavyokokotolewa, na usahihi wake",
    "Figure": "Takwimu", "Yours": "Yako", "Average": "Wastani", "Weight": "Uzito", "Effect": "Athari",
    "Starting point (intercept)": "Mahali pa kuanzia (intercept)", "Total (log-odds)": "Jumla (log-odds)",
    "Gross margin": "Kiwango cha faida ghafi", "Net margin": "Kiwango cha faida halisi",
    "Break-even sales": "Mauzo ya kurudisha gharama", "Margin of safety": "Kiwango cha usalama",
    "Months of stock": "Miezi ya bidhaa", "Average sale": "Wastani wa mauzo", "M-Pesa share": "Sehemu ya M-Pesa",
    "Is it accurate? The evidence": "Je, ni sahihi? Ushahidi", "Your track record": "Rekodi yako",
    "Your data and privacy": "Data yako na faragha", "Data integrity: keeping the figures right": "Uadilifu wa data: kuweka takwimu sahihi",
    "Privacy": "Faragha", "Data integrity": "Uadilifu wa data", "Your figures": "Takwimu zako", "The risk %": "Asilimia ya hatari",
    "Distress model": "Modeli ya dhiki", "ML, statistics or rules?": "ML, takwimu au kanuni?",
    // navigation and common
    "Skip to content": "Ruka hadi maudhui", "Admin": "Msimamizi", "Dashboard": "Dashibodi",
    "How it works": "Jinsi inavyofanya kazi", "Help": "Msaada", "Account": "Akaunti", "Log out": "Toka",
    "Install app": "Sakinisha programu", "Business": "Biashara", "Choose business": "Chagua biashara",
    "Loading your figures…": "Inapakia takwimu zako…", "Cancel": "Ghairi", "Confirm": "Thibitisha",
    "Show": "Onyesha", "Hide": "Ficha", "Later": "Baadaye", "Not now": "Si sasa", "Continue": "Endelea",
    "Pro": "Pro", "Edit": "Hariri", "Month": "Mwezi", "Sales": "Mauzo", "Costs": "Gharama",
    "Profit / loss": "Faida / hasara", "Profit": "Faida", "Loss": "Hasara", "Email": "Barua pepe",
    "Mobile number": "Nambari ya simu", "Password": "Nenosiri", "Send a new code": "Tuma msimbo mpya",
    "Send again": "Tuma tena", "6-digit code": "Msimbo wa tarakimu 6",
    "Biashara Check is decision support, not a guarantee. Your figures are not shared with lenders or anyone else.":
      "Biashara Check ni msaada wa kufanya maamuzi, si hakikisho. Takwimu zako hazishirikiwi na wakopeshaji wala mtu mwingine.",
    // dashboard header and actions
    "No businesses yet.": "Bado hakuna biashara.",
    "Go to admin": "Nenda kwa msimamizi",
    "Download report (PDF)": "Pakua ripoti (PDF)", "Reports (PDF)": "Ripoti (PDF)", "Reports": "Ripoti",
    "Monthly summary": "Muhtasari wa mwezi", "Business report": "Ripoti ya biashara", "Download": "Pakua",
    "Period": "Kipindi", "6 months": "Miezi 6", "12 months": "Miezi 12", "24 months": "Miezi 24", "All": "Yote",
    "Preparing…": "Inaandaa…", "Email me": "Nitumie kwa barua pepe", "Sending…": "Inatuma…",
    "your email once you confirm it": "barua pepe yako ukishaithibitisha", "Your report is downloading.": "Ripoti yako inapakuliwa.", "Get Biashara Pro": "Pata Biashara Pro",
    "PDF files to keep, print or share. Your figures are never sent to anyone by Biashara Check.": "Faili za PDF za kuhifadhi, kuchapisha au kushiriki. Biashara Check haitumi takwimu zako kwa mtu yeyote.",
    "Your latest month, the risk check, and a chart and table of the last 12 months. One or two pages.": "Mwezi wako wa mwisho, ukaguzi wa hatari, na chati na jedwali la miezi 12 iliyopita. Kurasa moja au mbili.", "Summary for lenders": "Muhtasari kwa wakopeshaji", "Report (PDF)": "Ripoti (PDF)", "For lenders": "Kwa wakopeshaji",
    "Confirm your email.": "Thibitisha barua pepe yako.", "We sent a 6-digit code to": "Tumetuma msimbo wa tarakimu 6 kwa",
    "Confirm your mobile number.": "Thibitisha nambari yako ya simu.", "We'll text a 6-digit code to": "Tutatuma SMS ya msimbo wa tarakimu 6 kwa",
    "Text me a code": "Nitumie msimbo kwa SMS",
    "Then you can reset your password by SMS too.": "Kisha unaweza kuweka upya nenosiri lako kwa SMS pia.",
    "It lets you reset your password yourself. Check your spam folder if you can't see it.": "Inakuwezesha kuweka upya nenosiri lako mwenyewe. Angalia folda ya spam usipoiona.",
    "The study team needs them to confirm accounts, and you need them to reset your password.": "Timu ya utafiti inazihitaji kuthibitisha akaunti, nawe unazihitaji kuweka upya nenosiri lako.",
    "Create a business account in the admin section, or ask an owner to sign up on the login page.": "Fungua akaunti ya biashara katika sehemu ya msimamizi, au mwombe mmiliki ajisajili kwenye ukurasa wa kuingia.", "6-digit code from the SMS": "Msimbo wa tarakimu 6 kutoka kwa SMS",
    "Add your email and mobile number.": "Ongeza barua pepe na nambari yako ya simu.", "Add them now": "Ziongeze sasa",
    "How is Biashara Check working for you?": "Biashara Check inakusaidiaje?",
    "Rate it in 2 minutes: it helps the study.": "Ipe alama kwa dakika 2: inasaidia utafiti.", "Give feedback": "Toa maoni",
    // start card
    "Start with your past months": "Anza na miezi yako iliyopita",
    "Add at least 3 months of sales and expenses to get your first risk check. 12 months gives the most reliable result.":
      "Ongeza angalau miezi 3 ya mauzo na matumizi ili upate ukaguzi wako wa kwanza wa hatari. Miezi 12 inatoa matokeo ya kuaminika zaidi.",
    "Type them in": "Ziandike", "Upload from Excel": "Pakia kutoka Excel",
    "One month at a time, using the form. Good if you keep a sales book.": "Mwezi mmoja kwa wakati, kwa fomu. Inafaa ukiwa na daftari la mauzo.",
    "Many months at once, using our template. Good if your records are on a computer.": "Miezi mingi kwa pamoja, kwa kiolezo chetu. Inafaa rekodi zako zikiwa kwenye kompyuta.",
    // risk card
    "Your risk check": "Ukaguzi wako wa hatari",
    "High risk of a loss in the next 3 months": "Hatari kubwa ya hasara katika miezi 3 ijayo",
    "Moderate risk of a loss in the next 3 months": "Hatari ya wastani ya hasara katika miezi 3 ijayo",
    "Low risk of a loss in the next 3 months": "Hatari ndogo ya hasara katika miezi 3 ijayo",
    "Moderate risk: watch your costs": "Hatari ya wastani: chunga gharama zako",
    "High": "Juu", "Moderate": "Wastani", "Low": "Chini",
    "High risk": "Hatari kubwa", "Moderate risk": "Hatari ya wastani", "Low risk": "Hatari ndogo",
    "The main reasons": "Sababu kuu", "Warning signs": "Dalili za hatari",
    "chance of a loss month in the next 3 months": "uwezekano wa mwezi wa hasara katika miezi 3 ijayo",
    "risk of a loss in the next 3 months": "hatari ya hasara katika miezi 3 ijayo",
    "Latest month at a glance": "Mwezi wa mwisho kwa muhtasari", "What's working for you": "Kinachokusaidia",
    "What's keeping your risk low": "Kinachoweka hatari yako chini", "Worth keeping an eye on": "Cha kuangalia",
    "Your risk check, month by month": "Ukaguzi wako wa hatari, mwezi kwa mwezi",
    "Model risk unavailable": "Utabiri wa modeli haupatikani",
    "Your last 3 months added up to a loss. Unless something changes, the next 3 are likely to as well.":
      "Miezi yako 3 iliyopita ilileta hasara. Usipobadilisha kitu, miezi 3 ijayo huenda ikawa hivyo pia.",
    "You are still making a profit, but warning signs are building up.": "Bado unapata faida, lakini dalili za hatari zinaongezeka.",
    "Your recent months are profitable and we see no strong warning signs.": "Miezi yako ya karibuni ina faida na hatuoni dalili kubwa za hatari.",
    "We compare your last 3 months with the 3 before them. 12 months or more gives the most reliable result.":
      "Tunalinganisha miezi yako 3 iliyopita na 3 iliyotangulia. Miezi 12 au zaidi inatoa matokeo ya kuaminika zaidi.",
    "Early check using a simple rule. The full AI prediction with its top 3 reasons will appear here once the model is trained.":
      "Ukaguzi wa mapema kwa kanuni rahisi. Utabiri kamili wa AI pamoja na sababu zake 3 kuu utaonekana hapa modeli ikishafunzwa.",
    "List your three biggest costs. Ask suppliers for a better price, or drop items that sell slowly.":
      "Orodhesha gharama zako tatu kubwa. Omba wasambazaji bei nafuu, au acha bidhaa zinazouzwa polepole.",
    "Check whether supplier prices went up while your selling prices stayed the same.":
      "Angalia kama bei za wasambazaji zilipanda huku bei zako za kuuza zikibaki zilezile.",
    "Plan repayments before taking more credit, and avoid buying slow stock on credit.":
      "Panga marejesho kabla ya kuchukua mkopo zaidi, na epuka kununua bidhaa zinazouzwa polepole kwa mkopo.",
    "Follow up money customers owe you, and hold off purchases that can wait.":
      "Fuatilia pesa unazodai wateja, na sitisha ununuzi unaoweza kusubiri.",
    // charts, stats, records
    "Profit or loss each month": "Faida au hasara kila mwezi", "Choose a chart": "Chagua chati",
    "Bar": "Nguzo", "Line": "Mstari", "Area": "Eneo", "Pie": "Duara", "Histogram": "Histogramu", "Table": "Jedwali",
    "Last 6 months": "Miezi 6 iliyopita", "Last 12 months": "Miezi 12 iliyopita", "All months": "Miezi yote",
    "Where your sales went": "Mauzo yako yalikoenda", "Cost of goods": "Gharama ya bidhaa", "Running expenses": "Matumizi ya uendeshaji",
    "How money came in": "Pesa zilivyoingia", "By M-Pesa": "Kwa M-Pesa", "Cash and other": "Pesa taslimu na nyingine",
    "Months with a profit or a loss": "Miezi ya faida au hasara", "Break-even": "Bila faida wala hasara",
    "Months when money owed went up or down": "Miezi ambayo deni lilipanda au kushuka", "Went up": "Lilipanda", "Went down": "Lilishuka", "No change": "Halikubadilika",
    "Your costs: more than your sales": "Gharama zako: zaidi ya mauzo yako", "sales": "mauzo", "costs": "gharama", "received": "zilizoingia", "months": "miezi", "changes": "mabadiliko",
    "The whole period at once. Hover or tap a slice to see its amount.": "Kipindi chote kwa pamoja. Gusa kipande uone kiasi chake.",
    "How many months fell into each range. Tall bars show what a typical month looks like.": "Idadi ya miezi katika kila kiwango. Nguzo ndefu zinaonyesha mwezi wa kawaida.",
    "Every month's figures, newest first.": "Takwimu za kila mwezi, za karibuni kwanza.",
    "Profit or loss": "Faida au hasara", "Cash left over each month": "Pesa iliyobaki kila mwezi", "Cash left over": "Pesa iliyobaki",
    "Sales and costs each month": "Mauzo na gharama kila mwezi", "Sales and costs": "Mauzo na gharama",
    "Money you owe at month end": "Deni lako mwisho wa mwezi", "Profit per 100 shillings sold": "Faida kwa kila shilingi 100 za mauzo",
    "Margin": "Faida kwa 100", "Money owed": "Deni",
    "Loss months": "Miezi ya hasara", "No losses so far": "Hakuna hasara hadi sasa",
    "Your records": "Rekodi zako", "Spotted a mistake? Choose Edit on that month.": "Umeona kosa? Chagua Hariri kwenye mwezi huo.",
    "Show latest 6 months": "Onyesha miezi 6 ya mwisho",
    // entry form
    "Add a month": "Ongeza mwezi", "Upload CSV": "Pakia CSV", "M-Pesa": "M-Pesa",
    "Change any figure, then save. The month itself can't be changed.": "Badilisha takwimu yoyote, kisha hifadhi. Mwezi wenyewe hauwezi kubadilishwa.",
    "Total sales": "Jumla ya mauzo", "Cost of goods sold": "Gharama ya bidhaa zilizouzwa",
    "What you paid for the stock you sold": "Ulicholipia bidhaa ulizouza", "Running expenses": "Matumizi ya uendeshaji",
    "Rent, wages, power, transport…": "Kodi, mishahara, umeme, usafiri…", "Cash": "Pesa taslimu",
    "Money received": "Pesa zilizoingia", "Money paid out": "Pesa zilizotoka", "Received by M-Pesa": "Zilizopokelewa kwa M-Pesa",
    "(optional)": "(si lazima)", "Stock, debt and number of sales": "Bidhaa, madeni na idadi ya mauzo",
    "Stock value at month end": "Thamani ya bidhaa mwisho wa mwezi", "Stock value": "Thamani ya bidhaa",
    "Money you owe": "Pesa unazodaiwa", "Loans, supplier credit, chama loans…": "Mikopo, madeni ya wasambazaji, mikopo ya chama…",
    "Number of sales": "Idadi ya mauzo", "Profit this month": "Faida mwezi huu", "Cash left over": "Pesa iliyobaki",
    "Save month": "Hifadhi mwezi", "Save changes": "Hifadhi mabadiliko", "Save anyway": "Hifadhi hata hivyo",
    "Delete this month": "Futa mwezi huu",
    "Please double-check these figures. If they're right, press Save anyway.": "Tafadhali hakiki takwimu hizi. Kama ziko sawa, bonyeza Hifadhi hata hivyo.",
    "Total sales is 0. Was the business closed this month?": "Jumla ya mauzo ni 0. Je, biashara ilifungwa mwezi huu?",
    "Cost of goods sold is much higher than total sales. Check you didn't type stock bought instead.":
      "Gharama ya bidhaa zilizouzwa ni kubwa sana kuliko mauzo. Hakikisha hukuandika bidhaa ulizonunua badala yake.",
    "Running expenses are much higher than total sales.": "Matumizi ya uendeshaji ni makubwa sana kuliko mauzo.",
    "Money received is more than 3 times your sales. Did a loan or personal money come in?":
      "Pesa zilizoingia ni zaidi ya mara 3 ya mauzo yako. Je, mkopo au pesa zako binafsi ziliingia?",
    "Received by M-Pesa is more than all money received.": "Zilizopokelewa kwa M-Pesa ni zaidi ya pesa zote zilizoingia.",
    "Money paid out is more than 3 times your costs. Did you repay a loan or buy a lot of stock?":
      "Pesa zilizotoka ni zaidi ya mara 3 ya gharama zako. Je, ulilipa mkopo au ulinunua bidhaa nyingi?",
    "Choose a CSV file first.": "Chagua faili ya CSV kwanza.", "Choose your file first.": "Chagua faili yako kwanza.",
    "Read my file": "Soma faili yangu", "Spreadsheet (CSV or Excel)": "Jedwali (CSV au Excel)", "Importing…": "Inaingiza…",
    "Check which column is which": "Hakiki safu ipi ni ipi", "Which column is which?": "Safu ipi ni ipi?",
    "Not in my file": "Haipo kwenye faili yangu", "No dates in my file": "Hakuna tarehe kwenye faili yangu",
    "Choose another file": "Chagua faili nyingine", "Nothing new to import": "Hakuna jipya la kuingiza",
    "Almost there.": "Karibu tumemaliza.", "Amounts in KES.": "Kiasi kwa KES.", "New": "Mpya", "Already saved": "Imeshahifadhiwa",
    "Your file has figures but no dates.": "Faili yako ina takwimu lakini haina tarehe.",
    "First row is the month of": "Mstari wa kwanza ni mwezi wa",
    "We couldn't tell which column has your sales. Choose it below.": "Hatukuweza kujua safu yenye mauzo yako. Ichague hapa chini.",
    "Change a box and we read the file again straight away. Nothing is saved until you press Import.": "Badilisha kisanduku na tunasoma faili tena mara moja. Hakuna kinachohifadhiwa hadi ubonyeze Ingiza.", "Uploading…": "Inapakia…",
    "Upload records": "Pakia rekodi", "The file had no new months.": "Faili haikuwa na miezi mipya.",
    "Download the template": "Pakua kiolezo", "and open it in Excel.": "na uifungue kwa Excel.",
    "Fill one row per month. Write months like 2025-06.": "Jaza mstari mmoja kwa kila mwezi. Andika miezi kama 2025-06.",
    "Save it as": "Ihifadhi kama", ", then choose it below.": ", kisha uichague hapa chini.", "CSV file": "Faili ya CSV",
    "Months you already saved are skipped, so uploading the same file twice is safe.":
      "Miezi uliyokwisha hifadhi inarukwa, kwa hivyo kupakia faili moja mara mbili ni salama.",
    // M-Pesa statement
    "Fill in M-Pesa figures from your statement": "Jaza takwimu za M-Pesa kutoka kwa taarifa yako",
    "See Biashara Pro": "Ona Biashara Pro", "Statement (PDF or CSV)": "Taarifa (PDF au CSV)",
    "Statement password": "Nenosiri la taarifa", "Read statement": "Soma taarifa", "Reading…": "Inasoma…",
    "Usually your ID number. Used once to open the file, never saved.": "Kwa kawaida ni nambari yako ya kitambulisho. Inatumika mara moja kufungua faili, haihifadhiwi.",
    "What we found": "Tulichopata", "Use": "Tumia", "Received": "Zilizopokelewa", "Payments": "Malipo",
    "Update months": "Sasisha miezi", "Another file": "Faili nyingine", "Choose your statement first.": "Chagua taarifa yako kwanza.",
    "Check the months, then press Update.": "Hakiki miezi, kisha bonyeza Sasisha.",
    "Tick the months to update": "Weka alama kwenye miezi ya kusasisha", "M-Pesa figures updated.": "Takwimu za M-Pesa zimesasishwa.",
    // verification messages
    "Enter the 6-digit code from the SMS.": "Weka msimbo wa tarakimu 6 kutoka kwa SMS.",
    "Enter the 6-digit code from the email.": "Weka msimbo wa tarakimu 6 kutoka kwa barua pepe.",
    "Mobile number confirmed.": "Nambari ya simu imethibitishwa.", "Email confirmed. Thank you.": "Barua pepe imethibitishwa. Asante.",
    "New code sent. It expires in 15 minutes.": "Msimbo mpya umetumwa. Unaisha baada ya dakika 15.",
    "Code sent. It can take a minute to arrive.": "Msimbo umetumwa. Unaweza kuchukua dakika moja kufika.",
    "Please log in.": "Tafadhali ingia.",
    // tour
    "Welcome to Biashara Check": "Karibu Biashara Check", "Add your months": "Ongeza miezi yako",
    "Read your risk check": "Soma ukaguzi wako wa hatari", "Watch the trend": "Fuatilia mwenendo",
    "Your figures stay yours": "Takwimu zako ni zako", "Skip": "Ruka", "Back": "Rudi", "Next": "Endelea",
    "Go to my dashboard": "Nenda kwenye dashibodi yangu", "Add my first month": "Ongeza mwezi wangu wa kwanza",
    "Each month you add your sales and costs. Biashara Check looks at the last few months and tells you if the next three are heading toward a loss, early enough to do something about it.":
      "Kila mwezi unaongeza mauzo na gharama zako. Biashara Check inaangalia miezi michache iliyopita na kukuambia kama mitatu ijayo inaelekea hasara, mapema ili uchukue hatua.",
    "Add a month after it ends. Type the figures from your sales book, upload many months at once from Excel, or, with Biashara Pro, read them from your M-Pesa statement.":
      "Ongeza mwezi ukishaisha. Andika takwimu kutoka daftari lako la mauzo, pakia miezi mingi kwa pamoja kutoka Excel, au, kwa Biashara Pro, zisome kutoka taarifa yako ya M-Pesa.",
    "After 3 months you get your first check: low, moderate or high risk of a loss. When there are warning signs, each one comes with something practical you can do.":
      "Baada ya miezi 3 unapata ukaguzi wa kwanza: hatari ndogo, ya wastani au kubwa ya hasara. Kukiwa na dalili za hatari, kila moja inakuja na hatua unayoweza kuchukua.",
    "Charts show profit, sales and costs, cash and money owed month by month. Spotted a mistake? Choose Edit on that month in Your records.":
      "Chati zinaonyesha faida, mauzo na gharama, pesa taslimu na madeni mwezi kwa mwezi. Umeona kosa? Chagua Hariri kwenye mwezi huo katika Rekodi zako.",
    "Only you and the study team can see your figures. They're never shared with lenders. The more months you add, the more reliable your check: 12 months is best.":
      "Ni wewe na timu ya utafiti tu mnaoweza kuona takwimu zako. Hazishirikiwi kamwe na wakopeshaji. Ukiongeza miezi mingi, ukaguzi wako unaaminika zaidi: miezi 12 ni bora.",
    // account page
    "Your account": "Akaunti yako", "Contact and messages": "Mawasiliano na ujumbe",
    "Password and security": "Nenosiri na usalama", "Delete account": "Futa akaunti", "Saved.": "Imehifadhiwa.", "Choose your own password.": "Chagua nenosiri lako mwenyewe.",
    "Choose a plan": "Chagua mpango", "M-Pesa number to pay from": "Nambari ya M-Pesa ya kulipia",
    "Pay with M-Pesa": "Lipa kwa M-Pesa", "Check your phone": "Angalia simu yako", "Your payments": "Malipo yako",
    "You'll get a prompt on this phone. Enter your M-Pesa PIN there. We never see your PIN.":
      "Utapata ombi kwenye simu hii. Weka PIN yako ya M-Pesa hapo. Hatuoni PIN yako kamwe.",
    "Contact details": "Mawasiliano", "Code from the email": "Msimbo kutoka kwa barua pepe", "Confirm email": "Thibitisha barua pepe",
    "Confirm your mobile number by SMS": "Thibitisha nambari yako ya simu kwa SMS", "Code from the SMS": "Msimbo kutoka kwa SMS",
    "Confirm number": "Thibitisha nambari", "Change email or mobile number": "Badilisha barua pepe au nambari ya simu",
    "Your password": "Nenosiri lako", "Save contact details": "Hifadhi mawasiliano",
    "Messages from Biashara Check": "Ujumbe kutoka Biashara Check",
    "Sent to your confirmed email, and by SMS to your confirmed mobile number.": "Hutumwa kwa barua pepe yako iliyothibitishwa, na kwa SMS kwa nambari yako iliyothibitishwa.",
    "Monthly report": "Ripoti ya kila mwezi", "Email me my report as a PDF when I add a month": "Nitumie ripoti yangu kama PDF ninapoongeza mwezi",
    "Reminders": "Vikumbusho", "Remind me early each month to add last month's figures": "Nikumbushe mapema kila mwezi kuongeza takwimu za mwezi uliopita",
    "Risk alerts": "Tahadhari za hatari", "Tell me straight away if my risk of a loss goes up": "Niambie mara moja hatari yangu ya hasara ikipanda",
    "Language": "Lugha", "Rate Biashara Check": "Ipe alama Biashara Check",
    "What did you like most?": "Ulipenda nini zaidi?", "What was confusing?": "Nini kilikuchanganya?", "What would you add?": "Ungeongeza nini?",
    "Send feedback": "Tuma maoni", "Change password": "Badilisha nenosiri", "Current password": "Nenosiri la sasa",
    "New password": "Nenosiri jipya", "Type the new password again": "Andika nenosiri jipya tena",
    "Recovery code": "Msimbo wa kurejesha", "Make a new recovery code": "Tengeneza msimbo mpya wa kurejesha",
    "Delete my account": "Futa akaunti yangu", "Want a copy first?": "Unataka nakala kwanza?",
    "Download my figures (CSV)": "Pakua takwimu zangu (CSV)", "I want to delete my account": "Nataka kufuta akaunti yangu",
    "Delete my account for good": "Futa akaunti yangu kabisa", "to confirm": "kuthibitisha", "Type": "Andika",
    // login page
    "Spot a loss before it reaches your cash box.": "Tambua hasara kabla haijafika kwenye kasha lako la pesa.",
    "Add your monthly sales and expenses. We look at the last few months and warn you if the next three are heading toward a loss.":
      "Ongeza mauzo na matumizi yako ya kila mwezi. Tunaangalia miezi michache iliyopita na kukuonya kama mitatu ijayo inaelekea hasara.",
    "Example shop": "Duka la mfano",
    "Profit is falling month after month. Check supplier prices before it turns into a loss.":
      "Faida inashuka mwezi baada ya mwezi. Angalia bei za wasambazaji kabla haijageuka hasara.",
    "Works with a sales book, Excel or your M-Pesa statement": "Inafanya kazi na daftari la mauzo, Excel au taarifa yako ya M-Pesa",
    "Your figures are never shared with lenders": "Takwimu zako hazishirikiwi kamwe na wakopeshaji",
    "Log in": "Ingia", "SME-001 or name@gmail.com": "SME-001 au name@gmail.com", "Create account": "Fungua akaunti", "Business code or email": "Msimbo wa biashara au barua pepe",
    "Forgot your password?": "Umesahau nenosiri?", "Reset your password": "Weka upya nenosiri lako",
    "How do you want to reset it?": "Ungependa kuliweka upya vipi?", "Email me": "Nitumie barua pepe", "Text me": "Nitumie SMS",
    "Send code": "Tuma msimbo", "6-digit code from the email": "Msimbo wa tarakimu 6 kutoka kwa barua pepe",
    "At least 8 characters.": "Angalau herufi 8.", "Set new password": "Weka nenosiri jipya", "Back to log in": "Rudi kuingia",
    "Check your email": "Angalia barua pepe yako", "Confirm and create account": "Thibitisha na ufungue akaunti",
    "Change my details": "Badilisha maelezo yangu", "Account type": "Aina ya akaunti", "Business owner": "Mmiliki wa biashara",
    "Study admin": "Msimamizi wa utafiti", "Choose a business code": "Chagua msimbo wa biashara", "Type of business": "Aina ya biashara",
    "Started trading": "Ilianza biashara",
    "Letters, numbers and dashes. Don't use your name or phone number.": "Herufi, nambari na vistari. Usitumie jina lako wala nambari ya simu.",
    "We don't ask for your name or ID number. Your business gets a code, and you log in with that code or your email.":
      "Hatuulizi jina lako wala nambari ya kitambulisho. Biashara yako inapata msimbo, na unaingia kwa msimbo huo au barua pepe yako.",
    "We'll send a code to confirm it. Used to reset your password.": "Tutatuma msimbo kuithibitisha. Inatumika kuweka upya nenosiri lako.",
    "Next, we'll email you a code to confirm your address. Your account is created once you enter it.":
      "Kisha, tutakutumia msimbo kwa barua pepe kuthibitisha anwani yako. Akaunti yako inafunguliwa ukiuweka.",
    "The code works for 15 minutes. Can't find it? Look in your spam or promotions folder.":
      "Msimbo unafanya kazi kwa dakika 15. Huuoni? Angalia folda ya spam au matangazo.",
    "Your account has been deleted.": "Akaunti yako imefutwa.",
    // business types
    "Retail shop / duka": "Duka la rejareja", "Wholesale / distributor": "Jumla / msambazaji", "Other services": "Huduma nyingine",
    "Food, hotel or restaurant": "Chakula, hoteli au mgahawa", "Farming and agribusiness": "Kilimo na biashara ya kilimo",
    "Manufacturing or processing": "Utengenezaji au usindikaji", "Salon, barber or beauty": "Saluni, kinyozi au urembo",
    "Clothes, tailoring or shoes": "Nguo, ushonaji au viatu", "Hardware and building materials": "Vifaa na vifaa vya ujenzi",
    "Phones, electronics or repairs": "Simu, vifaa vya elektroniki au matengenezo", "M-Pesa agent or money services": "Wakala wa M-Pesa au huduma za pesa",
    "Transport, boda boda or logistics": "Usafiri, boda boda au usafirishaji", "Chemist, pharmacy or clinic": "Duka la dawa au kliniki",
    "School, tuition or training": "Shule, masomo ya ziada au mafunzo", "Cyber cafe, printing or ICT": "Cyber, uchapishaji au TEHAMA",
    "Something else": "Kitu kingine",
  };

  const MONTHS = { Sept: "Sep", Jan: "Jan", Feb: "Feb", Mar: "Mac", Apr: "Apr", May: "Mei", Jun: "Jun", Jul: "Jul", Aug: "Ago", Sep: "Sep", Oct: "Okt", Nov: "Nov", Dec: "Des",
    January: "Januari", February: "Februari", March: "Machi", April: "Aprili", June: "Juni", July: "Julai", August: "Agosti",
    September: "Septemba", October: "Oktoba", November: "Novemba", December: "Desemba" };
  const mon = s => s.replace(/\b(January|February|March|April|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec)\b/g, m => MONTHS[m]);
  const sector = s => SW[s] || s;

  // [pattern, replacement function] for sentences with numbers, months or names in them
  const PATTERNS = [
    [/^(\d+) months?$/, n => `Miezi ${n}`],
    [/^Your risk check: next (\d+) months?$/, n => `Ukaguzi wako wa hatari: miezi ${n} ijayo`],
    [/^(High|Moderate|Low) risk of a loss in the next (\d+) months?$/, (b, n) => `Hatari ${{ High: "kubwa", Moderate: "ya wastani", Low: "ndogo" }[b]} ya hasara katika miezi ${n} ijayo`],
    [/^chance of a loss month in the next (\d+) months?$/, n => `uwezekano wa mwezi wa hasara katika miezi ${n} ijayo`],
    [/^Looking from (.+) to (.+), based on your figures up to (.+)\.$/, (a, b, c) => `Kuanzia ${mon(a)} hadi ${mon(b)}, kwa takwimu zako hadi ${mon(c)}.`],
    [/^Only 3 months is available until the study team updates the risk model\. The check below covers the next 3 months\.$/,
      () => "Miezi 3 pekee inapatikana hadi timu ya utafiti isasishe modeli ya hatari. Ukaguzi ulio chini ni wa miezi 3 ijayo."],
    [/^(\d+) months? \(to (.+)\)$/, (n, m) => `Miezi ${n} (hadi ${mon(m)})`],
    [/^(\d+)% chance of at least one loss month between (.+) and (.+) \(the next (\d+) months\)\.$/,
      (p, a, b, n) => `Uwezekano wa ${p}% wa angalau mwezi mmoja wa hasara kati ya ${mon(a)} na ${mon(b)} (miezi ${n} ijayo).`],
    [/^(\d+)% chance that (.+) is a loss month\.$/, (p, m) => `Uwezekano wa ${p}% kwamba ${mon(m)} utakuwa mwezi wa hasara.`],
    [/^Show all (\d+) figures$/, n => `Onyesha takwimu zote ${n}`],
    [/^Show fewer figures$/, () => "Onyesha takwimu chache"],
    [/^(\w+ \d{4})\. Loss months so far: (\d+) of (\d+)\.$/, (m, a, b) => `${mon(m)}. Miezi ya hasara hadi sasa: ${a} kati ya ${b}.`],
    [/^Sales minus cost of goods \((\d+)% of sales\)$/, n => `Mauzo toa gharama ya bidhaa (${n}% ya mauzo)`],
    [/^Rule: (.+)$/, r => `Kanuni: ${r}`],
    [/^Our model puts the chance of at least one loss month in the next 3 months at (\d+)%, based on your figures up to (.+)\.$/,
      (p, m) => `Modeli yetu inakadiria uwezekano wa angalau mwezi mmoja wa hasara katika miezi 3 ijayo kuwa ${p}%, kwa kutumia takwimu zako hadi ${mon(m)}.`],
    [/^Prediction by the (.+) model \((.+)\)\. Reasons come from SHAP: they show what moved your risk up or down\. Decision support, not a guarantee\.$/,
      (n, v) => `Utabiri wa modeli ya ${n} (${v}). Sababu zinatoka SHAP: zinaonyesha kilichopandisha au kushusha hatari yako. Msaada wa maamuzi, si hakikisho.`],
    [/^Step (\d+) of (\d+)$/, (a, b) => `Hatua ${a} kati ya ${b}`],
    [/^Add (\w+ \d{4})$/, m => `Ongeza ${mon(m)}`],
    [/^Edit (\w+ \d{4})$/, m => `Hariri ${mon(m)}`],
    [/^Editing (\w+ \d{4})$/, m => `Unahariri ${mon(m)}`],
    [/^Add (\d+) more months? to get your first check$/, n => `Ongeza miezi ${n} zaidi upate ukaguzi wako wa kwanza`],
    [/^(.+)\. (\d+) months? saved, latest (.+)\.$/, (s, n, m) => `${sector(s)}. Miezi ${n} imehifadhiwa, ya mwisho ${mon(m)}.`],
    [/^(.+)\. No figures saved yet\.$/, s => `${sector(s)}. Bado hakuna takwimu.`],
    [/^What you can do: (.*)$/s, t => `Unachoweza kufanya: ${SW[t] || t}`],
    [/^What you can do:\s*$/, () => "Unachoweza kufanya: "],
    [/^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sept?|Oct|Nov|Dec)$/, m => mon(m)],
    [/^Sent to (\S+)\. It can take a minute to arrive; check spam if you can't see it\.$/, e => `Imetumwa kwa ${e}. Inaweza kuchukua dakika moja kufika; angalia spam usipoiona.`],
    [/^We found (\d+) months?, (.+) to (.+)\.$/, (n, a, b) => `Tumepata miezi ${n}, ${mon(a)} hadi ${mon(b)}.`],
    [/^How we read your file \((\d+)\)$/, n => `Jinsi tulivyosoma faili yako (${n})`],
    [/^Import (\d+) months?$/, n => `Ingiza miezi ${n}`],
    [/^Based on your figures up to (.+)\.$/, m => `Kwa kutumia takwimu zako hadi ${mon(m)}.`],
    [/^Cash left over in (\w+)$/, m => `Pesa iliyobaki ${mon(m)}`],
    [/^(.+) (more|less) than (\w+(?: \d{4})?)$/, (a, d, m) => `${a} ${d === "more" ? "zaidi ya" : "chini ya"} ${mon(m)}`],
    [/^(Up|Down) (\d+)% on (\w+(?: \d{4})?)$/, (d, n, m) => `${d === "Up" ? "Juu" : "Chini"} ${n}% kuliko ${mon(m)}`],
    [/^Profit in (\w+)$/, m => `Faida ${mon(m)}`],
    [/^Sales in (\w+)$/, m => `Mauzo ${mon(m)}`],
    [/^Same as (.+)$/, m => `Sawa na ${mon(m)}`],
    [/^Last loss: (.+)$/, m => `Hasara ya mwisho: ${mon(m)}`],
    [/^(\d+) of (\d+)$/, (a, b) => `${a} kati ya ${b}`],
    [/^Show all (\d+) months$/, n => `Onyesha miezi yote ${n}`],
    [/^Saved (.+?)\. Next: (.+)\.$/, (a, b) => `Umehifadhi ${mon(a)}. Unaofuata: ${mon(b)}.`],
    [/^Saved (.+?)\. You're up to date\.$/, a => `Umehifadhi ${mon(a)}. Uko sawa hadi sasa.`],
    [/^Updated (\w+ \d{4})\.$/, a => `Umesasisha ${mon(a)}.`],
    [/^Deleted (.+)\.$/, a => `Umefuta ${mon(a)}.`],
    [/^Yes, delete (.+) for good$/, a => `Ndiyo, futa ${mon(a)} kabisa`],
    [/^Update (\d+) months?$/, n => `Sasisha miezi ${n}`],
    [/^Added (\d+) months?, (.+) to (.+)\.$/, (n, a, b) => `Umeongeza miezi ${n}, ${mon(a)} hadi ${mon(b)}.`],
    [/^Costs grew (\d+)% while sales grew only (\d+)% over the last 3 months\.$/, (a, b) => `Gharama zilipanda ${a}% huku mauzo yakipanda ${b}% tu katika miezi 3 iliyopita.`],
    [/^Costs grew (\d+)% while sales fell (\d+)% over the last 3 months\.$/, (a, b) => `Gharama zilipanda ${a}% huku mauzo yakishuka ${b}% katika miezi 3 iliyopita.`],
    [/^Sales fell (\d+)% but costs only fell (\d+)% over the last 3 months\.$/, (a, b) => `Mauzo yalishuka ${a}% lakini gharama zilishuka ${b}% tu katika miezi 3 iliyopita.`],
    [/^From every 100 shillings of sales you now keep (-?\d+), down from (-?\d+)\.$/, (a, b) => `Kutoka kila shilingi 100 za mauzo sasa unabaki na ${a}, kutoka ${b}.`],
    [/^Money you owe rose from (.+) to (.+)\.$/, (a, b) => `Deni lako lilipanda kutoka ${a} hadi ${b}.`],
    [/^More cash went out than came in over the last 3 months \((.+)\)\.$/, a => `Pesa zilizotoka zilizidi zilizoingia katika miezi 3 iliyopita (${a}).`],
    [/^Sales are ([\d.]+) times last month's\. Check for an extra zero\.$/, a => `Mauzo ni mara ${a} ya mwezi uliopita. Angalia kama kuna sifuri ya ziada.`],
    [/^Sales are less than a third of last month's\. Check for a missing zero\.$/, () => "Mauzo ni chini ya theluthi moja ya mwezi uliopita. Angalia kama sifuri imekosekana."],
    [/^That month hasn't finished yet\. (?:Add it once it's over\. )?The latest you can add is (.+)\.$/, a => `Mwezi huo bado haujaisha. Wa mwisho unaoweza kuongeza ni ${mon(a)}.`],
    [/^Fill in: (.+)$/, a => `Jaza: ${a.split(", ").map(x => SW[x] || x).join(", ")}`],
    [/^Use numbers only in: (.+)$/, a => `Tumia nambari tu katika: ${a.split(", ").map(x => SW[x] || x).join(", ")}`],
  ];

  function tr(text) {
    const lead = text.match(/^\s*/)[0], tail = text.match(/\s*$/)[0];
    const core = text.trim();
    if (!core) return null;
    if (SW[core]) return lead + SW[core] + tail;
    for (const [re, fn] of PATTERNS) {
      const m = core.match(re);
      if (m) return lead + fn(...m.slice(1)) + tail;
    }
    return null;
  }

  const ATTRS = ["placeholder", "aria-label", "title"];
  const orig = new WeakMap();   // text node -> English text
  const done = new WeakMap();   // text node -> the Kiswahili we put there
  let lang = read(), observer = null;

  function doText(n) {
    const p = n.parentNode;
    if (!p || /^(SCRIPT|STYLE|TEXTAREA|CODE)$/.test(p.nodeName) || p.closest?.("[data-no-i18n]")) return;
    if (done.get(n) === n.nodeValue) return;           // our own change
    const t = tr(n.nodeValue);
    if (t === null) return;
    orig.set(n, n.nodeValue);
    n.nodeValue = t;
    done.set(n, t);
  }
  function doAttrs(el) {
    for (const a of ATTRS) {
      const v = el.getAttribute(a);
      if (!v) continue;
      const key = "data-en-" + a;
      if (el.getAttribute(key + "-sw") === v) continue;
      const t = tr(v);
      if (t === null) continue;
      el.setAttribute(key, v);
      el.setAttribute(key + "-sw", t);
      el.setAttribute(a, t);
    }
  }
  function walk(root) {
    if (root.nodeType === 3) return doText(root);
    if (root.nodeType !== 1 && root.nodeType !== 9) return;
    if (root.nodeType === 1) {
      if (/^(SCRIPT|STYLE|TEXTAREA)$/.test(root.nodeName) || root.closest("[data-no-i18n]")) return;
      doAttrs(root);
    }
    const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
    let n;
    while ((n = w.nextNode())) n.nodeType === 3 ? doText(n) : doAttrs(n);
  }
  function restore() {
    const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
    let n;
    while ((n = w.nextNode())) {
      if (n.nodeType === 3) {
        if (done.get(n) === n.nodeValue && orig.has(n)) n.nodeValue = orig.get(n);
        done.delete(n);
      } else {
        for (const a of ATTRS) {
          const key = "data-en-" + a;
          if (n.hasAttribute(key)) {
            if (n.getAttribute(a) === n.getAttribute(key + "-sw")) n.setAttribute(a, n.getAttribute(key));
            n.removeAttribute(key); n.removeAttribute(key + "-sw");
          }
        }
      }
    }
    if (document.title !== titleEn && document.title === tr(titleEn)?.trim()) document.title = titleEn;
  }
  let titleEn = document.title;

  function start() {
    if (observer) return;
    walk(document.body);
    const tt = tr(titleEn); if (tt) document.title = tt;
    observer = new MutationObserver(list => {
      for (const m of list) {
        if (m.type === "characterData") doText(m.target);
        else if (m.type === "attributes") doAttrs(m.target);
        else m.addedNodes.forEach(walk);
      }
    });
    observer.observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ATTRS });
  }
  function stop() {
    if (observer) { observer.disconnect(); observer = null; }
    restore();
  }

  function apply() {
    document.documentElement.lang = lang;
    lang === "sw" ? start() : stop();
    const b = document.getElementById("lang-btn");
    if (b) {
      const [full, short] = lang === "sw" ? ["English", "EN"] : ["Kiswahili", "SW"];
      b.innerHTML = `<span class="wide-only">${full}</span><span class="narrow-only">${short}</span>`;
      b.setAttribute("aria-label", lang === "sw" ? "Switch to English" : "Badilisha lugha kuwa Kiswahili");
      b.lang = lang === "sw" ? "en" : "sw";
    }
  }

  async function set(v, save = true) {
    v = v === "sw" ? "sw" : "en";
    if (v === lang) return;
    lang = v; write(v); apply();
    if (save && !/\/login$/.test(location.pathname)) {
      await fetch("/auth/settings", { method: "PUT", headers: { "Content-Type": "application/json" }, credentials: "same-origin",
                                      body: JSON.stringify({ language: v }) }).catch(() => {});
    }
    document.dispatchEvent(new CustomEvent("languagechange", { detail: v }));
  }

  function addButton() {
    if (document.getElementById("lang-btn")) return;
    const nav = document.querySelector(".nav") || document.querySelector("[data-lang-slot]");
    if (!nav) return;
    const b = document.createElement("button");
    b.id = "lang-btn"; b.type = "button"; b.className = "nav-link lang-link";
    b.setAttribute("data-no-i18n", "");
    b.addEventListener("click", () => set(lang === "sw" ? "en" : "sw"));
    nav.prepend(b);
  }

  window.I18N = {
    get lang() { return lang; },
    set,
    sync: v => set(v, false),        // language saved on the account (from /auth/me)
    t: s => (lang === "sw" ? (tr(s) ?? s) : s),
  };

  const init = () => { titleEn = document.title; addButton(); apply(); };
  document.readyState === "loading" ? document.addEventListener("DOMContentLoaded", init) : init();
})();
