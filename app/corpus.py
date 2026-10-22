"""Synthetic mailbox for the embedding heads.

These rows are generated. They are not copied from a QA report, an eval file,
or the sample mailbox. A held-out split is a hash of the text, so the same
sentence never sits in both sides.
"""

from __future__ import annotations

import zlib

LABELS = ("lead", "support", "invoice", "recruiter", "spam", "personal", "other")


def _row(label: str, text: str, outage: int = 0, explicit: int = 0, negated: int = 0) -> dict:
    return {
        "label": label,
        "text": " ".join(text.split()),
        "outage": outage,
        "explicit": explicit,
        "negated": negated,
    }


def _held(text: str) -> bool:
    return zlib.crc32(text.encode("utf-8")) % 5 == 0


def rows() -> list[dict]:
    """A few thousand varied messages in more than ten languages."""
    built: list[dict] = []
    services = (
        "a Python service",
        "a HubSpot and Slack sync",
        "a Shopify order inbox",
        "a booking form",
        "a client portal",
        "an invoice reminder",
    )
    amounts = ("$4,200", "€3,600", "£2,400", "$8,000 a month", "TRY 90000", "PKR 250,000", "SEK 12000")
    companies = (
        "Northmill Clinic",
        "Harbor Tea",
        "Kite Payments",
        "Lumen Dental",
        "Fieldnote Studio",
        "Cedar Freight",
    )
    for company in companies:
        for service in services:
            for amount in amounts[:4]:
                built.append(_row("lead", f"Hello, {company} needs {service}. Could you quote it? Budget is {amount}."))
                built.append(_row("lead", f"We would like a statement of work for {service}. {company} can spend {amount}."))
                built.append(_row(
                    "lead",
                    f"A colleague referred me. {company} is looking for help with {service}. No price yet.",
                ))
    # Contracts and first contacts without a budget, written out so the grammar holds.
    static = [
        ("lead", "Bonjour, nous cherchons un devis pour relier la boîte mail à notre CRM. Pas de budget fixé."),
        ("lead", "Bonjour, le contrat pour la phase 2 est prêt. Le budget est de 14 000 euros."),
        ("lead", "Guten Tag, wir brauchen ein Angebot für eine Automationsstrecke. Budget 6.000 Euro."),
        ("lead", "Guten Tag, der Vertrag ist unterschrieben. Der Rahmen liegt bei 9.000 Euro."),
        ("lead", "Hola, ¿nos puedes cotizar un flujo entre el correo y la tienda? Tenemos 3.000 dólares."),
        ("lead", "Hola, adjunto el alcance firmado. El presupuesto es de 5.000 euros."),
        ("lead", "Olá, precisamos de um orçamento para automatizar os pedidos. Temos R$ 12.000."),
        ("lead", "Olá, um amigo indicou você. Queremos ajuda com o inbox, sem valor definido."),
        ("lead", "Merhaba, teklif istiyoruz. Aylık çalışma için bütçe 90000 TL."),
        ("lead", "Merhaba, sizi bir meslektaş önerdi. Sözleşme taslağını konuşalım."),
        ("lead", "你好，我们想要一个报价，把邮箱和客户系统连起来。预算 8 万元。"),
        ("lead", "你好，这是一份工作说明，预算还没定，想先聊聊范围。"),
        ("lead", "こんにちは。メールと顧客管理をつなぐ見積もりをお願いします。予算は120万円です。"),
        ("lead", "こんにちは。契約書の前に、作業範囲だけ相談したいです。"),
        ("lead", "مرحبا، نريد عرض سعر لربط البريد مع النظام. الميزانية 15,000 درهم."),
        ("lead", "مرحبا، زميلك رشحك. نحتاج مساعدة في الحجوزات دون ميزانية بعد."),
        ("lead", "Hallo, we zoeken een offerte voor een koppeling tussen inbox en CRM. Budget €4.500."),
        ("lead", "Hej, vi behöver en offert för att koppla mejlen till bokningen. Budget 18 000 kr."),
        ("lead", "Cześć, prosimy o wycenę automatyzacji zamówień. Budżet 20 000 zł."),
        ("lead", "A partner suggested I write. We want a retainer for the inbox work, no number yet."),
        ("support", "The export button on my settings page is broken. Not urgent at all."),
        ("support", "No rush. Drafted replies come back in English and I need them in French."),
        ("support", "I still cannot log in. This is the same bug, not a new project."),
        ("support", "Pas urgent. Le bouton exporter ne marche que pour moi."),
        ("support", "Keine Eile. Das Logo sitzt ein paar Pixel daneben."),
        ("support", "Acil değil. Raporlar İngilizce geliyor, Türkçe olsun."),
        ("support", "急ぎではありません。送信済みの色を直してください。"),
        ("support", "不着急。导出按钮只有我这边是坏的。"),
        ("support", "Sin prisa. El filtro de la bandeja no guarda mi elección."),
        ("support", "Sem pressa. O botão de exportar falha só na minha conta."),
        ("support", "No es urgente. La sesión se cierra cuando cambio de pestaña."),
        ("support", "Not urgent. How do I rename a saved view?"),
        ("invoice", "Invoice 4412 is attached. Amount due USD 1,150. Pay to the account on the invoice."),
        ("invoice", "This is a past due notice for invoice 1042. The amount due is $2,000."),
        ("invoice", "Payment received for the workshop. The transfer of $980 posted this morning."),
        ("invoice", "Rechnung 2201. Offener Betrag 640 Euro. Bitte auf das angegebene Konto."),
        ("invoice", "Factura 19 adjunta. Importe pendiente 640 euros."),
        ("invoice", "Fatura 88. Valor em aberto R$ 2.400."),
        ("invoice", "請求書 551 の金額は 8 万円です。"),
        ("invoice", "发票 309 已附上，应付 2,400 元。"),
        ("invoice", "Your receipt for the April seat. Payment of $89 was charged to the card."),
        ("invoice", "The domain renewal for harbor.example is due. Amount due $18."),
        ("invoice", "Subscription renewal. Your plan renews at €29 on the card we have."),
        ("recruiter", "I am a recruiter. We have an open role. The base salary is $140,000."),
        ("recruiter", "We are hiring for a Head of Automation. Compensation is AED 45,000 a month. This is not a project."),
        ("recruiter", "Talent partner here. The OTE for this role is €120,000. Happy to send the spec."),
        ("recruiter", "Votre CV nous intéresse. Le salaire de base est 90 000 euros. Ce n'est pas une mission."),
        ("recruiter", "Wir stellen ein. Das Gehalt liegt bei 85.000 Euro im Jahr."),
        ("recruiter", "採用のご連絡です。年収は 900 万円です。案件のご相談ではありません。"),
        ("recruiter", "İşe alım için yazıyorum. Maaş aylık 80.000 TL. Proje teklifi değil."),
        ("spam", "You have been selected for a webinar. Unsubscribe at the link below."),
        ("spam", "Monthly newsletter: three trends. Manage preferences or unsubscribe."),
        ("spam", "Newsletter de la semaine. Lien de désinscription en bas."),
        ("spam", "Monatsnewsletter. Hier abmelden."),
        ("spam", "Boletín semanal. Puedes darte de baja abajo."),
        ("spam", "Haftalık bülten. Abonelikten çıkmak için tıklayın."),
        ("spam", "周报已发送。退订链接在页脚。"),
        ("spam", "週刊ニュースです。配信停止はこちら。"),
        ("personal", "Are you free for lunch on Thursday? No work talk."),
        ("personal", "Thanks for the birthday note. See you at the weekend."),
        ("personal", "Je passe en ville demain, un café ?"),
        ("personal", "Hast du am Freitag Zeit für einen Spaziergang?"),
        ("other", "FYI the file you asked about is in the shared drive. No action needed."),
        ("other", "Looping you in so you have the thread. Nothing to do today."),
        ("other", "Pour info, le compte rendu est archivé."),
    ]
    for label, text in static:
        built.append(_row(label, text))
    # Outages: customer impact, including paraphrases that skip the word "down".
    outages = [
        "Checkout returns server errors for every order and we are losing sales.",
        "No client can finish a booking. The page spins and never confirms.",
        "Shipment notices have not gone out. Customers are asking where the orders are. I need you on this now.",
        "Confirmation links show an error for every patient. Please fix this right away.",
        "The booking system is offline and we cannot take bookings.",
        "El sistema de pedidos está caído y no entra nada.",
        "O site está fora do ar e ninguém consegue pagar.",
        "Sipariş ekranı çalışmıyor. Müşteriler kasada bekliyor.",
        "La caisse est hors service. Personne ne peut encaisser.",
        "Die Kasse ist ausgefallen. Kein Kunde kann bezahlen.",
        "De kassa is offline en bestellingen lopen niet door.",
        "Kassan är nere och kunder kan inte betala.",
        "结账页面一直报错，顾客无法下单。",
        "予約画面が落ちていて、誰も予約できません。",
        "نظام الحجز متوقف ولا يستطيع أحد إتمام الطلب.",
        "Every customer sees a blank page on checkout. Orders have stopped.",
        "The portal throws an error on each login for the whole team, not just one person.",
        "Patients cannot open the confirmation. The link fails for all of them.",
        "The shipping emails never left the queue. Buyers are waiting on tracking numbers.",
        "Tracking messages did not send. Every buyer is asking where the order is.",
        "Outbound shipment mail is stuck. Customers cannot see tracking.",
        "The notice emails failed to send and the whole customer list is waiting.",
        "Every checkout ends in a server error and the shop has stopped taking orders.",
        "Booking attempts spin forever and no client can finish one.",
    ]
    for text in outages:
        built.append(_row("support", text, outage=1, explicit=1))
        built.append(_row("support", "From our side: " + text, outage=1))
    # Explicit urgency that is only a deadline, not an outage.
    deadlines = [
        "Could you send the proposal before 5pm today? Nothing is broken.",
        "We need the quote by end of day. The site is up.",
        "Please reply today, the board meets tomorrow. This is a pricing question.",
        "Necesitamos el presupuesto hoy antes de las 5. El sistema funciona.",
        "Merci de répondre avant 18h. Aucune panne.",
        "Bitte das Angebot bis heute Abend. Es ist nichts ausgefallen.",
    ]
    for text in deadlines:
        built.append(_row("lead", text, explicit=1))
    # Negation must beat the word urgent and must not look like an outage.
    negations = [
        "Not urgent at all. The export on the settings page is broken for my user only.",
        "No rush, whenever you have time. I cannot find the old filter.",
        "Acil değil. Sadece bir raporun dili yanlış.",
        "急ぎではありません。自分の画面の色だけおかしいです。",
        "Pas urgent, pas de panne. Une faute dans le pied de page.",
        "Keine Eile und kein Ausfall. Nur eine Frage zur Rechnungskopie.",
        "No es urgente. Es una duda sobre mi propia contraseña.",
        "不着急，也不是故障。想问一下怎么改名字。",
    ]
    for text in negations:
        built.append(_row("support", text, negated=1))
    # Repeat static rows with a neutral prefix so the held-out split sees new strings
    # of the same shape, without copying any external mailbox.
    prefixes = ("Note:", "Quick one.", "Following up.", "Second try.", "From the team.")
    seed = list(built)
    for prefix in prefixes:
        for item in seed:
            if item["label"] in {"lead", "support", "invoice", "recruiter", "spam"}:
                text = f"{prefix} {item['text']}"
                built.append(_row(item["label"], text, item["outage"], item["explicit"], item["negated"]))
    deduped = []
    seen = set()
    for item in built:
        if item["text"] in seen:
            continue
        seen.add(item["text"])
        item["heldout"] = _held(item["text"])
        deduped.append(item)
    return deduped


# Prototypes for the money-movement centroid. These are the concept, in several
# languages, not lines from a review set.
LURES = [
    "Pay via this secure link so we can release the funds.",
    "Verify your withdrawal method and confirm the payout account.",
    "Please update the bank account. Future payments should use the new IBAN.",
    "Neue Bankverbindung. Bitte künftige Zahlungen auf das neue Konto überweisen.",
    "Veuillez utiliser les nouvelles coordonnées bancaires pour les virements.",
    "Actualice la cuenta bancaria y envíe los pagos a este IBAN.",
    "Banka hesabı değişti. Bundan sonraki ödemeleri yeni IBAN'a gönderin.",
    "Buy Google Play gift cards and reply with the card numbers.",
    "Kauf bitte Gutscheinkarten und schick die Codes zurück.",
    "Verify your wallet and send the USDT to the address below.",
    "Your invoice is attached. View and pay here.",
    "Confirm your payment method or the payout stays on hold.",
    "请把以后的付款转到新的银行账户。",
    "新しい口座に振り込んでください。",
    "يرجى تحويل المبلغ إلى الحساب البنكي الجديد.",
    "The wallet address for the payout has changed. Verify it now.",
]

# Letterhead invoices and ordinary commercial mail. The centroid should sit far from these.
BENIGN_MONEY = [
    "Invoice 19 is attached. The amount due is $640. Pay to the account printed on the invoice.",
    "Amount due £1,200. Sort code and account are in the footer of this note.",
    "Could you quote a Python service? Budget is $8,000 a month.",
    "The export button is broken. Not urgent.",
    "Payment received. No further amount due.",
    "We are hiring. The salary is $140,000. This is not a client project.",
    "Unsubscribe from this newsletter.",
    "Rechnung beigefügt. Bitte begleichen Sie den offenen Betrag auf das angegebene Konto.",
]
