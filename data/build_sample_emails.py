"""Write data/sample_emails.json. Run once from the repo root; the JSON is the labeled set."""

import json
from pathlib import Path

EMAILS = [
    {
        "id": "m01",
        "from_name": "Jane Cole",
        "from_email": "jane.cole@acmerobotics.com",
        "subject": "Looking for a Python partner for a monthly retainer",
        "received_at": "2026-10-21T13:05:00Z",
        "label": "lead",
        "name": "Jane Cole",
        "company": "Acme Robotics",
        "budget": "$8,000",
        "intent": "hire an automation freelancer",
        "body": """Hello Asad,

We are looking for a freelancer to take over the automations between our inbox, HubSpot, and Slack. The work is a Python service plus a monthly retainer so the flows stay healthy.

Our budget is $8,000/mo to start, and we can begin this month if the fit is right.

Thanks,
Jane Cole
Operations Director
Acme Robotics
jane.cole@acmerobotics.com
""",
    },
    {
        "id": "m02",
        "from_name": "Marcus Hale",
        "from_email": "marcus.hale@brightlinedental.com",
        "subject": "Can we book a demo next Tuesday?",
        "received_at": "2026-10-21T15:40:00Z",
        "label": "lead",
        "name": "Marcus Hale",
        "company": "Brightline Dental",
        "budget": "$4,500",
        "intent": "book a discovery call",
        "body": """Asad,

I am interested in a demo of an inbox classifier that files new patient mail and opens a HubSpot contact. We can spend about $4,500 to start.

Would Tuesday at 10:30 work for a demo?

Thanks,
Marcus Hale
Founder
Brightline Dental
marcus.hale@brightlinedental.com
""",
    },
    {
        "id": "m03",
        "from_name": "Priya Shah",
        "from_email": "priya.shah@northwindlogistics.com",
        "subject": "RFP: inbox triage into HubSpot",
        "received_at": "2026-10-21T11:12:00Z",
        "label": "lead",
        "name": "Priya Shah",
        "company": "Northwind Logistics",
        "budget": "$15,000",
        "intent": "request a proposal",
        "body": """Hi Asad,

Please treat this as an RFP. We need a proposal and pricing for a Python service that reads a shared mailbox, classifies the mail with Claude, and writes qualified records into HubSpot.

The budget for the first release is $15,000. A short proposal by Friday is enough. No call needed yet.

Regards,
Priya Shah
Head of Operations
Northwind Logistics
priya.shah@northwindlogistics.com
""",
    },
    {
        "id": "m04",
        "from_name": "Elena Voss",
        "from_email": "elena.voss@studiomarlowe.com",
        "subject": "Discovery call about our inquiry inbox?",
        "received_at": "2026-10-20T16:20:00Z",
        "label": "lead",
        "name": "Elena Voss",
        "company": "Studio Marlowe",
        "budget": None,
        "intent": "book a discovery call",
        "body": """Hi Asad,

We are looking for someone to look at our inquiry inbox with us. Would you take a discovery call next week? I do not have a number yet. I want to see the shape of the work first.

Best,
Elena Voss
Studio Marlowe
elena.voss@studiomarlowe.com
""",
    },
    {
        "id": "m05",
        "from_name": "Tom Becker",
        "from_email": "tom.becker@beckerandco.com",
        "subject": "Could you quote a HubSpot and Python build?",
        "received_at": "2026-10-21T09:48:00Z",
        "label": "lead",
        "name": "Tom Becker",
        "company": "Becker & Co",
        "budget": "$6,000",
        "intent": "request a proposal",
        "body": """Asad,

Could you quote a HubSpot and Python build that files new business mail and creates the contact? Budget is around 6k. A one-page quote is perfect.

Thanks,
Tom Becker
Partner
Becker & Co
tom.becker@beckerandco.com
""",
    },
    {
        "id": "m06",
        "from_name": "Hannah Cho",
        "from_email": "hannah.cho@fieldnote.co",
        "subject": "Want to hire a freelancer to classify mail with Claude",
        "received_at": "2026-10-21T15:55:00Z",
        "label": "lead",
        "name": "Hannah Cho",
        "company": "Fieldnote",
        "budget": "$3,200",
        "intent": "hire an automation freelancer",
        "body": """Hello,

We want to hire a freelancer to classify inbound mail with Claude and drop the structured fields into our CRM. This is a contract, not a product question.

We can pay $3,200 for the first build.

Cheers,
Hannah Cho
Fieldnote
hannah.cho@fieldnote.co
""",
    },
    {
        "id": "m07",
        "from_name": "Omar Farouk",
        "from_email": "omar.farouk@qastravel.com",
        "subject": "Pricing for a GoHighLevel setup",
        "received_at": "2026-10-20T18:05:00Z",
        "label": "lead",
        "name": "Omar Farouk",
        "company": "Qasr Travel",
        "budget": "$2,500",
        "intent": "request a proposal",
        "body": """Hi Asad,

I need pricing for a GoHighLevel setup that captures website inquiries and writes them into the pipeline with a source tag. The ceiling for setup is $2,500.

Please send pricing when you can. I am not ready to book time yet.

Regards,
Omar Farouk
Owner
Qasr Travel
omar.farouk@qastravel.com
""",
    },
    {
        "id": "m08",
        "from_name": "Lena Ortiz",
        "from_email": "lena.ortiz@copperandrye.com",
        "subject": "Monthly retainer for client onboarding",
        "received_at": "2026-10-21T16:10:00Z",
        "label": "lead",
        "name": "Lena Ortiz",
        "company": "Copper & Rye",
        "budget": "$3,000",
        "intent": "hire an automation freelancer",
        "body": """Asad,

I would like a monthly retainer for the automations that onboard a new client: folder, CRM record, and a welcome sequence. The budget is $3,000 per month.

If you take retainers of that size, tell me how you like to start.

Thanks,
Lena Ortiz
Copper & Rye
lena.ortiz@copperandrye.com
""",
    },
    {
        "id": "m09",
        "from_name": "David Kim",
        "from_email": "david.kim@kimparcel.com",
        "subject": "Demo request: route web inquiries into the CRM",
        "received_at": "2026-10-21T08:30:00Z",
        "label": "lead",
        "name": "David Kim",
        "company": "Kim Parcel",
        "budget": None,
        "intent": "book a discovery call",
        "body": """Hi Asad,

Demo request. I want to see a workflow that routes web inquiries into the CRM and pings Slack. I am interested in a demo next week. No budget conversation until I have seen it.

Best,
David Kim
Kim Parcel
david.kim@kimparcel.com
""",
    },
    {
        "id": "m10",
        "from_name": "Sofia Berg",
        "from_email": "sofia.berg@bergaritekter.se",
        "subject": "Proposal request, first phase budget €9,000",
        "received_at": "2026-10-20T14:15:00Z",
        "label": "lead",
        "name": "Sofia Berg",
        "company": "Berg Arkitekter",
        "budget": "€9,000",
        "intent": "request a proposal",
        "body": """Hello Asad,

We would like a proposal for phase one of an inquiry desk. Our budget for the first phase is €9,000. Please include what you would run in Python and what you would leave to a person.

Kind regards,
Sofia Berg
Principal
Berg Arkitekter
sofia.berg@bergaritekter.se
""",
    },
    {
        "id": "m11",
        "from_name": "Chris Dalton",
        "from_email": "chris.dalton@daltonfreight.com",
        "subject": "Retainer for the automations we already run",
        "received_at": "2026-10-21T10:22:00Z",
        "label": "lead",
        "name": "Chris Dalton",
        "company": "Dalton Freight",
        "budget": "$5,500",
        "intent": "hire an automation freelancer",
        "body": """Asad,

We want to hire a freelancer on a retainer for the automations we already run. The stack is Python and HubSpot. Budget can sit at $5,500 a month.

Tell me if you have room.

Thanks,
Chris Dalton
Dalton Freight
chris.dalton@daltonfreight.com
""",
    },
    {
        "id": "m12",
        "from_name": "Amira Hassan",
        "from_email": "amira.hassan@lumenclinics.com",
        "subject": "Looking for a proposal to qualify inbound mail",
        "received_at": "2026-10-20T19:40:00Z",
        "label": "lead",
        "name": "Amira Hassan",
        "company": "Lumen Clinics",
        "budget": "$7,500",
        "intent": "request a proposal",
        "body": """Hi Asad,

We are looking for a proposal to qualify inbound mail before a coordinator touches it. Pull out the name, the clinic, the budget if they mention one, and the ask.

We have $7,500 set aside for the build.

Regards,
Amira Hassan
Director
Lumen Clinics
amira.hassan@lumenclinics.com
""",
    },
    {
        "id": "m13",
        "from_name": "Greg Poulos",
        "from_email": "greg.poulos@acmerobotics.com",
        "subject": "Can't log in to the client portal — error 403",
        "received_at": "2026-10-21T12:18:00Z",
        "label": "support",
        "name": "Greg Poulos",
        "company": "Acme Robotics",
        "budget": None,
        "intent": "restore account access",
        "body": """Hi Asad,

I can't log in to the client portal this morning. The page returns error 403 after I submit the form. I tried a second browser. Same result.

Can you restore the login?

Thanks,
Greg Poulos
Plant Manager
Acme Robotics
greg.poulos@acmerobotics.com
""",
    },
    {
        "id": "m14",
        "from_name": "Nina Patel",
        "from_email": "nina.patel@fieldnote.co",
        "subject": "Webhook stopped firing after we rotated the key",
        "received_at": "2026-10-21T09:05:00Z",
        "label": "support",
        "name": "Nina Patel",
        "company": "Fieldnote",
        "budget": None,
        "intent": "resolve a product issue",
        "body": """Asad,

The webhook stopped firing after we rotated the key last night. New submissions sit in the form tool and never reach the classifier. Nothing else in the account changed.

Please take a look when you are in.

Best,
Nina Patel
Fieldnote
nina.patel@fieldnote.co
""",
    },
    {
        "id": "m15",
        "from_name": "Alan Briggs",
        "from_email": "alan.briggs@northwindlogistics.com",
        "subject": "Bug: duplicate contacts landing in HubSpot",
        "received_at": "2026-10-21T15:20:00Z",
        "label": "support",
        "name": "Alan Briggs",
        "company": "Northwind Logistics",
        "budget": None,
        "intent": "resolve a product issue",
        "body": """Hi,

Bug report. The intake flow is creating duplicate contacts in HubSpot, two records for the same address about a minute apart. It started after yesterday's publish.

I need the duplicate path closed.

Regards,
Alan Briggs
Systems Coordinator
Northwind Logistics
alan.briggs@northwindlogistics.com
""",
    },
    {
        "id": "m16",
        "from_name": "Rachel Nguyen",
        "from_email": "rachel.nguyen@studiomarlowe.com",
        "subject": "How do I point approvals at a different Slack channel?",
        "received_at": "2026-10-20T15:48:00Z",
        "label": "support",
        "name": "Rachel Nguyen",
        "company": "Studio Marlowe",
        "budget": None,
        "intent": "resolve a product issue",
        "body": """Hi Asad,

How do I point approvals at a different Slack channel? The current one is not working for the producers. They miss the message because it lands in an old channel.

A short note on which node to edit is enough.

Thanks,
Rachel Nguyen
Producer
Studio Marlowe
rachel.nguyen@studiomarlowe.com
""",
    },
    {
        "id": "m17",
        "from_name": "Pete Alvarez",
        "from_email": "pete.alvarez@kimparcel.com",
        "subject": "The lead form is broken on mobile Safari",
        "received_at": "2026-10-21T07:55:00Z",
        "label": "support",
        "name": "Pete Alvarez",
        "company": "Kim Parcel",
        "budget": None,
        "intent": "resolve a product issue",
        "body": """Asad,

The lead form is broken on mobile Safari. Tapping submit does nothing. Desktop Chrome still posts. Customers on phones are bouncing.

This is a bug on the live page, not a request for new work.

Thanks,
Pete Alvarez
Kim Parcel
pete.alvarez@kimparcel.com
""",
    },
    {
        "id": "m18",
        "from_name": "Joyce Kim",
        "from_email": "joyce.kim@lumenclinics.com",
        "subject": "The receipt file won't download from the portal",
        "received_at": "2026-10-20T21:10:00Z",
        "label": "support",
        "name": "Joyce Kim",
        "company": "Lumen Clinics",
        "budget": None,
        "intent": "resolve a product issue",
        "body": """Hello,

The receipt file won't download from the portal. I get a blank screen instead of the PDF. I need last month's file for our bookkeeper.

The rest of the portal opens fine.

Regards,
Joyce Kim
Office Coordinator
Lumen Clinics
joyce.kim@lumenclinics.com
""",
    },
    {
        "id": "m19",
        "from_name": "Samir Das",
        "from_email": "samir.das@daltonfreight.com",
        "subject": "Outlook connector returns error 401 on every run",
        "received_at": "2026-10-21T06:40:00Z",
        "label": "support",
        "name": "Samir Das",
        "company": "Dalton Freight",
        "budget": None,
        "intent": "resolve a product issue",
        "body": """Hi Asad,

The Outlook connector returns error 401 on every run since this morning. The workflow used to read the shared mailbox without a problem. I did not change the flow.

Please repair the connection.

Thanks,
Samir Das
IT Coordinator
Dalton Freight
samir.das@daltonfreight.com
""",
    },
    {
        "id": "m20",
        "from_name": "Helen Zhou",
        "from_email": "helen.zhou@qastravel.com",
        "subject": "The classify job is failing on the model step",
        "received_at": "2026-10-20T17:25:00Z",
        "label": "support",
        "name": "Helen Zhou",
        "company": "Qasr Travel",
        "budget": None,
        "intent": "resolve a product issue",
        "body": """Asad,

The classify job is failing on the model step. The error text is "timeout talking to the model". Three runs in a row did this. The earlier steps succeed.

Can you see why that node is failing?

Best,
Helen Zhou
Qasr Travel
helen.zhou@qastravel.com
""",
    },
    {
        "id": "m21",
        "from_name": "Victor Lang",
        "from_email": "victor.lang@beckerandco.com",
        "subject": "Account locked and the password reset never arrives",
        "received_at": "2026-10-21T11:48:00Z",
        "label": "support",
        "name": "Victor Lang",
        "company": "Becker & Co",
        "budget": None,
        "intent": "restore account access",
        "body": """Hi,

My account is locked and the password reset never arrives. I requested it twice from the login page. I need to get into the approval queue before noon.

Thanks,
Victor Lang
Associate
Becker & Co
victor.lang@beckerandco.com
""",
    },
    {
        "id": "m22",
        "from_name": "Carla Mendes",
        "from_email": "carla.mendes@copperandrye.com",
        "subject": "Search is not working for my login",
        "received_at": "2026-10-20T13:05:00Z",
        "label": "support",
        "name": "Carla Mendes",
        "company": "Copper & Rye",
        "budget": None,
        "intent": "resolve a product issue",
        "body": """Hello Asad,

Search is not working for my login. Everyone else on the team can search the archive. Mine spins and returns no rows. I can still open a record if I have the link.

It is only my seat.

Thanks,
Carla Mendes
Producer
Copper & Rye
carla.mendes@copperandrye.com
""",
    },
    {
        "id": "m23",
        "from_name": "Accounts Payable",
        "from_email": "ap@brightlinedental.com",
        "subject": "Invoice INV-2041 — amount due USD 2,400, Net 15",
        "received_at": "2026-10-21T15:05:00Z",
        "label": "invoice",
        "name": None,
        "company": "Brightline Dental",
        "budget": "$2,400",
        "intent": "collect a payment",
        "body": """Hello,

Please process invoice INV-2041. Amount due: USD 2,400. Terms Net 15, from the date of this note.

The PDF is attached in the live mailbox. This copy lists the total only.

Regards,
Accounts Payable
Brightline Dental
ap@brightlinedental.com
""",
    },
    {
        "id": "m24",
        "from_name": "Northwind Accounts",
        "from_email": "accounts@northwindlogistics.com",
        "subject": "Remittance advice for invoice 1988",
        "received_at": "2026-10-21T08:10:00Z",
        "label": "invoice",
        "name": None,
        "company": "Northwind Logistics",
        "budget": "$6,200",
        "intent": "confirm remittance",
        "body": """Hello,

Remittance advice for invoice 1988. We sent payment this morning. Amount paid: USD 6,200. Please confirm remittance on your side and close the item.

Regards,
Northwind Accounts
Northwind Logistics
accounts@northwindlogistics.com
""",
    },
    {
        "id": "m25",
        "from_name": "Mara Ellison",
        "from_email": "mara.ellison@harborprint.co",
        "subject": "Past due notice, invoice 3310",
        "received_at": "2026-10-20T12:30:00Z",
        "label": "invoice",
        "name": "Mara Ellison",
        "company": "Harbor Print Co",
        "budget": "£890",
        "intent": "collect a payment",
        "body": """Hello,

This is a past due notice for invoice 3310. Amount due £890. Please pay this week so we can release the next print run.

The original invoice was dated 2 September.

Regards,
Mara Ellison
Accounts Manager
Harbor Print Co
mara.ellison@harborprint.co
""",
    },
    {
        "id": "m26",
        "from_name": "Ibrahim Sane",
        "from_email": "ibrahim.sane@sane.studio",
        "subject": "Please find attached invoice 4412",
        "received_at": "2026-10-21T04:20:00Z",
        "label": "invoice",
        "name": "Ibrahim Sane",
        "company": "Sane Studio",
        "budget": "$1,150",
        "intent": "collect a payment",
        "body": """Hi Asad,

Please find attached invoice 4412 for the workshop photography. Total USD 1,150. Pay to the account on the invoice when you can.

Thank you,
Ibrahim Sane
Sane Studio
ibrahim.sane@sane.studio
""",
    },
    {
        "id": "m27",
        "from_name": "Billing Desk",
        "from_email": "billing@paperlane.example",
        "subject": "Billing statement for Q3",
        "received_at": "2026-10-19T18:00:00Z",
        "label": "invoice",
        "name": None,
        "company": "Paperlane",
        "budget": "$3,300",
        "intent": "collect a payment",
        "body": """Hello,

Attached is the billing statement for Q3. Amount due $3,300. Terms Net 30.

Please reply if a line needs a purchase order number.

Regards,
Billing Desk
Paperlane
billing@paperlane.example
""",
    },
    {
        "id": "m28",
        "from_name": "Ruth Keller",
        "from_email": "ruth.keller@kellerandgray.com",
        "subject": "URGENT: invoice 1042 is 14 days past due",
        "received_at": "2026-10-21T13:40:00Z",
        "label": "invoice",
        "name": "Ruth Keller",
        "company": "Keller & Gray",
        "budget": "$2,000",
        "intent": "collect a payment",
        "body": """Hello,

I am writing because invoice 1042 is 14 days past due. The amount due is $2,000. Please pay it or tell me if the invoice is stuck with the wrong person.

I marked the subject urgent so it is seen. It is still a billing note.

Regards,
Ruth Keller
Controller
Keller & Gray
ruth.keller@kellerandgray.com
""",
    },
    {
        "id": "m29",
        "from_name": "Jonah Briggs",
        "from_email": "jonah.briggs@briggworkshop.com",
        "subject": "Payment received — thank you",
        "received_at": "2026-10-20T09:15:00Z",
        "label": "invoice",
        "name": "Jonah Briggs",
        "company": "Briggs Workshop",
        "budget": "$980",
        "intent": "confirm remittance",
        "body": """Hello Asad,

Payment received for the March workshop. The transfer of $980 posted this morning. I will close the file on our side. No further amount due.

Thanks,
Jonah Briggs
Controller
Briggs Workshop
jonah.briggs@briggworkshop.com
""",
    },
    {
        "id": "m30",
        "from_name": "Adeola Bankole",
        "from_email": "adeola.bankole@bankolelegal.com",
        "subject": "W-9 and invoice for March attached",
        "received_at": "2026-10-18T16:45:00Z",
        "label": "invoice",
        "name": "Adeola Bankole",
        "company": "Bankole Legal",
        "budget": "$4,800",
        "intent": "collect a payment",
        "body": """Hi,

W-9 and invoice for March are attached. Invoice 5501. Please pay USD 4,800 under Net 15.

Tell me if the vendor form needs a different legal name.

Regards,
Adeola Bankole
Counsel
Bankole Legal
adeola.bankole@bankolelegal.com
""",
    },
    {
        "id": "m31",
        "from_name": "Rewards Desk",
        "from_email": "claim@airdrop-rewards.example",
        "subject": "You've been selected for a bitcoin giveaway",
        "received_at": "2026-10-21T03:12:00Z",
        "label": "spam",
        "name": None,
        "company": None,
        "budget": None,
        "intent": "unsolicited promotion",
        "body": """Congratulations. You've been selected for a bitcoin giveaway worth a fortune.

Click below to claim before the timer ends. Unsubscribe at the bottom of this message if you do not want crypto alerts.

Rewards Desk
""",
    },
    {
        "id": "m32",
        "from_name": "Atlas SEO",
        "from_email": "grow@rank-atlas.example",
        "subject": "Dear Business Owner — rank on Google this month",
        "received_at": "2026-10-21T16:22:00Z",
        "label": "spam",
        "name": None,
        "company": None,
        "budget": None,
        "intent": "unsolicited promotion",
        "body": """Dear Business Owner,

We can rank on Google with our SEO package. Guaranteed page one or you pay nothing. Limited time offer for a handful of local firms.

Unsubscribe here if you would rather stay invisible.
""",
    },
    {
        "id": "m33",
        "from_name": "Health Offers",
        "from_email": "rx@overnight-offers.example",
        "subject": "Discount pharmacy shipped overnight",
        "received_at": "2026-10-19T02:04:00Z",
        "label": "spam",
        "name": None,
        "company": None,
        "budget": None,
        "intent": "unsolicited promotion",
        "body": """Private offer. Discount viagra and other pills shipped overnight, no prescription conversation.

Click below to claim the catalog. Unsubscribe if this landed in the wrong inbox.
""",
    },
    {
        "id": "m34",
        "from_name": "Home Income",
        "from_email": "join@home-income.example",
        "subject": "Work from home and earn $5,000 a week",
        "received_at": "2026-10-18T11:11:00Z",
        "label": "spam",
        "name": None,
        "company": None,
        "budget": "$5,000",
        "intent": "unsolicited promotion",
        "body": """Work from home and earn $5,000 a week with your phone. No experience. A coach is standing by.

This is a limited time offer. Unsubscribe if you are not ready to change your life.
""",
    },
    {
        "id": "m35",
        "from_name": "Security Notice",
        "from_email": "notice@mcafee-billing.example",
        "subject": "Your McAfee invoice is ready",
        "received_at": "2026-10-21T01:44:00Z",
        "label": "spam",
        "name": None,
        "company": None,
        "budget": None,
        "intent": "unsolicited promotion",
        "body": """Your McAfee invoice is ready. We could not charge the card on file.

Click below to claim the document and keep the subscription active. Unsubscribe from security notices.

This is an automated security message.
""",
    },
    {
        "id": "m36",
        "from_name": "Growth Bot",
        "from_email": "leo@pipeline-growth.example",
        "subject": "I help founders 10x your pipeline",
        "received_at": "2026-10-20T08:08:00Z",
        "label": "spam",
        "name": None,
        "company": None,
        "budget": None,
        "intent": "unsolicited promotion",
        "body": """Hey,

I help founders 10x your pipeline in 30 days with my cold email machine. Reply "yes" and I will send the deck.

Unsubscribe if you hate revenue.
""",
    },
    {
        "id": "m37",
        "from_name": "Prize Center",
        "from_email": "claims@prize-center.example",
        "subject": "Lottery beneficiary notice",
        "received_at": "2026-10-17T22:30:00Z",
        "label": "spam",
        "name": None,
        "company": None,
        "budget": None,
        "intent": "unsolicited promotion",
        "body": """Dear friend,

You are the beneficiary of a lottery inheritance held with our clearing partner. Reply with your full name and a copy of your passport to release the funds.

Unsubscribe is not available on this legal notice.
""",
    },
    {
        "id": "m38",
        "from_name": "Editorial Desk",
        "from_email": "editor@guest-posts.example",
        "subject": "Re: your website — guest post opportunity",
        "received_at": "2026-10-19T09:50:00Z",
        "label": "spam",
        "name": None,
        "company": None,
        "budget": None,
        "intent": "unsolicited promotion",
        "body": """Hi,

I found your website and I have a guest post that would rank. We write it, you publish it, we both win. Rates are friendly.

Unsubscribe if you do not accept contributed articles.
""",
    },
    {
        "id": "m39",
        "from_name": "Maya Chen",
        "from_email": "maya.chen@fieldandfern.com",
        "subject": "Production is down — checkout webhook is not taking orders",
        "received_at": "2026-10-21T15:48:00Z",
        "label": "urgent",
        "name": "Maya Chen",
        "company": "Field & Fern",
        "budget": None,
        "intent": "escalate an outage",
        "body": """Asad,

Production is down. The checkout webhook is not taking orders and the shop is showing an error to customers. This started 15 minutes ago. I need you on it now.

Please reply as soon as you see this.

Thanks,
Maya Chen
Founder
Field & Fern
maya.chen@fieldandfern.com
""",
    },
    {
        "id": "m40",
        "from_name": "Ops Team",
        "from_email": "ops@acmerobotics.com",
        "subject": "Server is down and every automation has stalled",
        "received_at": "2026-10-21T05:15:00Z",
        "label": "urgent",
        "name": None,
        "company": "Acme Robotics",
        "budget": None,
        "intent": "escalate an outage",
        "body": """Asad,

The server is down and every automation has stalled. The worker host does not answer. Please treat this as an outage.

We will stay by the phone.

Regards,
Ops Team
Acme Robotics
ops@acmerobotics.com
""",
    },
    {
        "id": "m41",
        "from_name": "Helen Cho",
        "from_email": "helen.cho@cho-counsel.com",
        "subject": "Need the DPA workflow finished by end of day",
        "received_at": "2026-10-21T16:05:00Z",
        "label": "urgent",
        "name": "Helen Cho",
        "company": "Cho Counsel",
        "budget": None,
        "intent": "meet a same-day deadline",
        "body": """Asad,

Counsel needs the DPA workflow finished by end of day. The client signs tomorrow morning and the packet has to include the generated schedule. This is a same-day deadline, not a new engagement.

Please confirm you can land it today.

Regards,
Helen Cho
Counsel
Cho Counsel
helen.cho@cho-counsel.com
""",
    },
    {
        "id": "m42",
        "from_name": "Luis Ortega",
        "from_email": "luis.ortega@brightlinedental.com",
        "subject": "ASAP: client demo in 2 hours and the CRM sync is failing",
        "received_at": "2026-10-21T14:02:00Z",
        "label": "urgent",
        "name": "Luis Ortega",
        "company": "Brightline Dental",
        "budget": None,
        "intent": "meet a same-day deadline",
        "body": """Asad,

ASAP. We have a client demo in 2 hours and the CRM sync is failing. The room is already booked. I need the sync healthy before we start, or a clear fallback if it will not be.

Please call me if you need a login.

Thanks,
Luis Ortega
Brightline Dental
luis.ortega@brightlinedental.com
""",
    },
    {
        "id": "m43",
        "from_name": "Grace Adeyemi",
        "from_email": "grace.adeyemi@northwindlogistics.com",
        "subject": "Sev-1: the billing workflow is sending duplicate charges",
        "received_at": "2026-10-21T02:28:00Z",
        "label": "urgent",
        "name": "Grace Adeyemi",
        "company": "Northwind Logistics",
        "budget": None,
        "intent": "escalate an outage",
        "body": """Asad,

Sev-1. The billing workflow is sending duplicate charges to customers who already paid. Please stop that workflow first, then tell me how many ran in the last hour.

I am on the bridge line.

Regards,
Grace Adeyemi
Controller
Northwind Logistics
grace.adeyemi@northwindlogistics.com
""",
    },
    {
        "id": "m44",
        "from_name": "Owen Park",
        "from_email": "owen.park@studiomarlowe.com",
        "subject": "The board is in the room — deck build failed",
        "received_at": "2026-10-20T20:10:00Z",
        "label": "urgent",
        "name": "Owen Park",
        "company": "Studio Marlowe",
        "budget": None,
        "intent": "meet a same-day deadline",
        "body": """Asad,

The board is in the room. The deck build failed and I need a fresh file within the hour. They are waiting on the numbers page.

Please send whatever you can regenerate first.

Thanks,
Owen Park
Producer
Studio Marlowe
owen.park@studiomarlowe.com
""",
    },
]


def main() -> None:
    path = Path(__file__).with_name("sample_emails.json")
    path.write_text(json.dumps(EMAILS, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {len(EMAILS)} emails to {path}")


if __name__ == "__main__":
    main()
