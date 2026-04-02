import base64
import io
import json
import random
import re
import smtplib
from email.mime.text import MIMEText
import pandas as pd
import streamlit as st
import time
from PIL import Image, ImageEnhance, ImageOps
import google.generativeai as genai
import firebase_admin
from firebase_admin import credentials, firestore

# --- Sayfa Ayarları ---
st.set_page_config(layout="wide", page_title="Cingöz", page_icon="🧿")

# --- CSS: Arayüz Düzenlemeleri ---
st.markdown("""
    <style>
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        header {visibility: hidden;}
        .block-container {
            padding-top: 1rem;
            max-width: 95% !important; 
            padding-left: 0rem !important;
            padding-right: 0rem !important;
        }

        [data-testid="stVerticalBlock"] > div:has(input) {
            background: linear-gradient(90deg, #e0f2fe 0%, #bae6fd 100%);
            padding: 15px;
            border-radius: 12px;
            border: 1px solid #7dd3fc;
        }
        .stTextInput input { background-color: white !important; }

        [data-testid="stTabs"] {
            margin-bottom: 0.5rem;
        }
        [data-testid="stTabs"] button[data-baseweb="tab"] {
            font-size: 0.95rem;
            font-weight: 600;
        }

        div[data-testid="stBaseButton-secondary"] {
            margin-top: 0px !important;
            margin-bottom: 0px !important;
            height: 45px;
        }

        /* Çıkış butonu header metni ile hizala */
        [data-testid="stHorizontalBlock"] > div:last-child .stButton {
            margin-top: 14px !important;
        }

        /* Web Tablosu Verilerini Ortalama */
        [data-testid="stDataFrame"] td {
            text-align: center !important;
        }
        [data-testid="stDataFrame"] th {
            text-align: center !important;
        }
    </style>
""", unsafe_allow_html=True)

# --- 1. Gemini API & Firebase Bağlantısı ---
if "GEMINI_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
else:
    st.error("⚠️ API Key Bulunamadı!")
    st.stop()

if not firebase_admin._apps:
    try:
        firebase_info = dict(st.secrets["firebase"])
        cred = credentials.Certificate(firebase_info)
        firebase_admin.initialize_app(cred)
    except Exception as e:
        st.error(f"Firebase Başlatma Hatası: {e}")
        st.stop()

try:
    db = firestore.client()
except:
    st.stop()

# --- OTP Mail Gönderme ---
def mail_gonder(alici_email, alici_ad, kod):
    try:
        icerik = f"""Merhaba {alici_ad},

Cingöz platformuna kayıt için doğrulama kodunuz:

🔐 {kod}

Bu kod 10 dakika geçerlidir.
Eğer kayıt talebinde bulunmadıysanız bu maili dikkate almayınız.

Cingöz uygulama Ekibi 🧿"""
        msg = MIMEText(icerik, "plain", "utf-8")
        msg['Subject'] = 'Cingöz - E-posta Doğrulama Kodu'
        msg['From'] = st.secrets["GMAIL_ADRES"]
        msg['To'] = alici_email
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(st.secrets["GMAIL_ADRES"], st.secrets["GMAIL_SIFRE"])
            smtp.sendmail(st.secrets["GMAIL_ADRES"], alici_email, msg.as_string())
        return True
    except Exception as e:
        st.error(f"Mail gönderilemedi: {e}")
        return False

# --- 2. Üst Satır Giriş Paneli ---
def login_header():
    if "user" not in st.session_state:
        tab1, tab2 = st.tabs(["🔑 Giriş Yap", "📝 Kayıt Ol"])

        with tab1:
            l_col1, l_col2, l_col3 = st.columns([2, 2, 1], gap="small")
            with l_col1:
                u_name = st.text_input("Kullanıcı Adı", placeholder="Kullanıcı Adı", label_visibility="collapsed", key="login_user")
            with l_col2:
                u_pass = st.text_input("Şifre", type="password", placeholder="Şifre", label_visibility="collapsed", key="login_pass")
            with l_col3:
                login_btn = st.button("Giriş Yap", use_container_width=True, key="login_btn")
            if login_btn:
                query = db.collection("users").where("kullanici_adi", "==", u_name).where("sifre", "==", u_pass).stream()
                user_data = None
                for doc in query:
                    user_data = doc.to_dict()
                    st.session_state["user_doc_id"] = doc.id
                if user_data:
                    st.session_state["user"] = u_name
                    st.session_state["kredi"] = user_data.get("kredi", 0)
                    st.rerun()
                else:
                    st.error("Hatalı giriş!")

        with tab2:
            # --- OTP doğrulama aşaması ---
            if st.session_state.get("otp_bekleniyor"):
                st.info(f"📧 **{st.session_state['bekleyen_email']}** adresine 6 haneli kod gönderildi. Lütfen kontrol edin.")
                o_col1, o_col2 = st.columns([2, 1], gap="small")
                with o_col1:
                    girilen_kod = st.text_input("Doğrulama Kodu", placeholder="6 haneli kod", label_visibility="collapsed", key="otp_input")
                with o_col2:
                    dogrula_btn = st.button("Kaydı Tamamla", use_container_width=True, key="dogrula_btn")

                if dogrula_btn:
                    otp_sure = st.session_state.get("otp_sure", 0)
                    if time.time() - otp_sure > 600:
                        st.error("⏱️ Kodun süresi doldu. Lütfen tekrar kayıt olun.")
                        for k in ["otp_bekleniyor", "bekleyen_email", "bekleyen_kayit", "otp_kod", "otp_sure"]:
                            st.session_state.pop(k, None)
                        st.rerun()
                    elif girilen_kod == str(st.session_state.get("otp_kod", "")):
                        kayit = st.session_state["bekleyen_kayit"]
                        db.collection("users").add({
                            "ad_soyad": kayit["ad_soyad"],
                            "email": kayit["email"],
                            "telefon": kayit["telefon"],
                            "kullanici_adi": kayit["kullanici_adi"],
                            "sifre": kayit["sifre"],
                            "kredi": 10,
                            "kayit_tarihi": firestore.SERVER_TIMESTAMP
                        })
                        for k in ["otp_bekleniyor", "bekleyen_email", "bekleyen_kayit", "otp_kod", "otp_sure"]:
                            st.session_state.pop(k, None)
                        st.success("✅ Kayıt tamamlandı! 10 deneme krediniz yüklendi. Giriş yapabilirsiniz.")
                    else:
                        st.error("❌ Kod hatalı, tekrar deneyin.")

                if st.button("↩️ Geri Dön", key="geri_btn"):
                    for k in ["otp_bekleniyor", "bekleyen_email", "bekleyen_kayit", "otp_kod", "otp_sure"]:
                        st.session_state.pop(k, None)
                    st.rerun()

            else:
                # --- Kayıt formu ---
                r_col1, r_col2, r_col3 = st.columns([2, 2, 2], gap="small")
                with r_col1:
                    r_adsoyad = st.text_input("Ad Soyad", placeholder="Ad Soyad", label_visibility="collapsed", key="reg_adsoyad")
                with r_col2:
                    r_email = st.text_input("E-posta", placeholder="E-posta", label_visibility="collapsed", key="reg_email")
                with r_col3:
                    r_tel = st.text_input("Telefon", placeholder="Telefon", label_visibility="collapsed", key="reg_tel")

                r_col4, r_col5, r_col6, r_col7 = st.columns([2, 2, 2, 1], gap="small")
                with r_col4:
                    r_name = st.text_input("Kullanıcı Adı", placeholder="Kullanıcı Adı", label_visibility="collapsed", key="reg_user")
                with r_col5:
                    r_pass = st.text_input("Şifre", type="password", placeholder="Şifre", label_visibility="collapsed", key="reg_pass")
                with r_col6:
                    r_pass2 = st.text_input("Şifre Tekrar", type="password", placeholder="Şifre Tekrar", label_visibility="collapsed", key="reg_pass2")
                with r_col7:
                    reg_btn = st.button("Kod Gönder", use_container_width=True, key="reg_btn")

                if reg_btn:
                    if not r_adsoyad or not r_email or not r_name or not r_pass:
                        st.error("Lütfen tüm alanları doldurun.")
                    elif not re.match(r"[^@]+@[^@]+\.[^@]+", r_email):
                        st.error("Geçerli bir e-posta girin.")
                    elif r_pass != r_pass2:
                        st.error("Şifreler eşleşmiyor.")
                    else:
                        # Kullanıcı adı kontrolü
                        mevcut_k = db.collection("users").where("kullanici_adi", "==", r_name).stream()
                        if any(True for _ in mevcut_k):
                            st.error("Bu kullanıcı adı zaten alınmış.")
                        else:
                            # E-posta kontrolü
                            mevcut_e = db.collection("users").where("email", "==", r_email).stream()
                            if any(True for _ in mevcut_e):
                                st.error("Bu e-posta ile zaten kayıt var.")
                            else:
                                otp = str(random.randint(100000, 999999))
                                if mail_gonder(r_email, r_adsoyad, otp):
                                    st.session_state["otp_kod"] = otp
                                    st.session_state["otp_sure"] = time.time()
                                    st.session_state["otp_bekleniyor"] = True
                                    st.session_state["bekleyen_email"] = r_email
                                    st.session_state["bekleyen_kayit"] = {
                                        "ad_soyad": r_adsoyad.strip().upper(),
                                        "email": r_email.strip(),
                                        "telefon": r_tel.strip(),
                                        "kullanici_adi": r_name.strip(),
                                        "sifre": r_pass
                                    }
                                    st.rerun()
    else:
        l_col1, l_col2, l_col3 = st.columns([4, 1, 1])
        l_col1.markdown(f"### 🧿 Cingöz Sınav Okuma Uygulaması | Hoş geldiniz, **{st.session_state['user']}**")
        kredi = st.session_state.get("kredi", 0)
        kredi_renk = "green" if kredi > 3 else "red"
        l_col2.markdown(f"<div style='text-align:center; padding-top:18px; font-weight:bold; color:{kredi_renk};'>🪙 {kredi} Kredi</div>", unsafe_allow_html=True)
        if l_col3.button("Çıkış Yap", use_container_width=True):
            del st.session_state["user"]
            st.rerun()

# --- 3. Yardımcı Fonksiyonlar ---
def optimize_for_gemini(pil_img: Image.Image) -> Image.Image:
    img = pil_img.convert('L')
    img = ImageOps.autocontrast(img)
    enhancer = ImageEnhance.Contrast(img)
    img = enhancer.enhance(1.8)

    if img.height > 750:
        h_percent = (750 / float(img.height))
        w_size = int((float(img.width) * float(h_percent)))
        img = img.resize((w_size, 750), Image.Resampling.LANCZOS)
    return img

def image_to_base64(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return base64.b64encode(buf.getvalue()).decode()

def show_lightbox_gallery(images: list, key_suffix):
    imgs_b64 = [image_to_base64(img) for img in images]
    thumbs_html = "".join([
        f'<img src="data:image/jpeg;base64,{b64}" '
        f'onclick="open_{key_suffix}(\'data:image/jpeg;base64,{b64}\')" '
        f'style="width:40px; height:60px; object-fit:cover; cursor:pointer; margin:4px; border-radius:6px; box-shadow: 0 2px 8px rgba(0,0,0,0.4);">'
        for b64 in imgs_b64
    ])
    html = f"""
    <style>
        body {{ margin: 0; padding: 0; overflow: hidden; background: transparent; }}
        #gallery {{ display: flex; flex-wrap: wrap; align-content: flex-start; }}
        .overlay {{ display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.98); z-index:999999; overflow:hidden; touch-action: none; }}
        .zoom-container {{ width: 100%; height: 100%; display: flex; justify-content: center; align-items: center; }}
        .zoom-img {{ max-width: 95%; max-height: 95%; transition: transform 0.05s linear; cursor: grab; user-select: none; -webkit-user-drag: none; }}
        .close-btn {{ position: absolute; top: 15px; right: 25px; color: white; font-size: 50px; font-weight: bold; cursor: pointer; z-index: 1000001; text-shadow: 0 0 10px black; }}
    </style>
    <div id="gallery">{thumbs_html}</div>
    <div id="overlay_{key_suffix}" class="overlay">
        <span class="close-btn" onclick="close_{key_suffix}()">&times;</span>
        <div class="zoom-container" id="container_{key_suffix}"><img id="img_{key_suffix}" class="zoom-img" src=""></div>
    </div>
    <script>
        let scale = 1, pannedX = 0, pannedY = 0, initialDist = -1, isDragging = false, startX, startY;
        const img = document.getElementById('img_{key_suffix}');
        const container = document.getElementById('container_{key_suffix}');
        function open_{key_suffix}(src) {{ img.src = src; document.getElementById('overlay_{key_suffix}').style.display = 'block'; scale = 1; pannedX = 0; pannedY = 0; updateTransform(); }}
        function close_{key_suffix}() {{ document.getElementById('overlay_{key_suffix}').style.display = 'none'; }}
        function updateTransform() {{ img.style.transform = `translate(${{pannedX}}px, ${{pannedY}}px) scale(${{scale}})`; }}
        container.addEventListener('wheel', (e) => {{ e.preventDefault(); scale *= (e.deltaY > 0 ? 0.9 : 1.1); scale = Math.min(Math.max(0.5, scale), 15); updateTransform(); }}, {{passive: false}});
        container.addEventListener('touchstart', (e) => {{ if (e.touches.length === 2) {{ initialDist = Math.hypot(e.touches[0].clientX - e.touches[1].clientX, e.touches[0].clientY - e.touches[1].clientY); }} else {{ isDragging = true; startX = e.touches[0].clientX - pannedX; startY = e.touches[0].clientY - pannedY; }} }}, {{passive: false}});
        container.addEventListener('touchmove', (e) => {{ e.preventDefault(); if (e.touches.length === 2 && initialDist > 0) {{ const currentDist = Math.hypot(e.touches[0].clientX - e.touches[1].clientX, e.touches[0].clientY - e.touches[1].clientY); scale *= (currentDist / initialDist); initialDist = currentDist; scale = Math.min(Math.max(0.5, scale), 15); updateTransform(); }} else if (isDragging) {{ pannedX = e.touches[0].clientX - startX; pannedY = e.touches[0].clientY - startY; updateTransform(); }} }}, {{passive: false}});
        container.addEventListener('mousedown', (e) => {{ isDragging = true; startX = e.clientX - pannedX; startY = e.clientY - pannedY; }});
        window.addEventListener('mousemove', (e) => {{ if (!isDragging) return; pannedX = e.clientX - startX; pannedY = e.clientY - startY; updateTransform(); }});
        window.addEventListener('touchend', () => {{ isDragging = false; initialDist = -1; }});
        window.addEventListener('mouseup', () => isDragging = false);
    </script>
    """
    st.components.v1.html(html, height=250)

# --- ANA AKIŞ ---
login_header()

if "user" in st.session_state:
    sinav_files = None
    s_imgs = []
    col1, col2, col3 = st.columns([1, 1, 1.2])

    with col1:
        st.subheader("1. Cevap Anahtarı")
        cevap_files = st.file_uploader("Yükle", type=["png", "jpg", "jpeg", "webp"], accept_multiple_files=True, key="c_u", label_visibility="collapsed")
        if cevap_files:
            c_imgs = [optimize_for_gemini(Image.open(f)) for f in cevap_files]
            show_lightbox_gallery(c_imgs, "cevap")

    with col2:
        st.subheader("2. Sınav Kağıtları")
        sinav_files_raw = st.file_uploader("Yükle", type=["png", "jpg", "jpeg", "webp"], accept_multiple_files=True, key="s_up", label_visibility="collapsed")

        if sinav_files_raw:
            dosya_adlari = [f.name for f in sinav_files_raw]
            tekrar_edenler = sorted(set(ad for ad in dosya_adlari if dosya_adlari.count(ad) > 1))
            if tekrar_edenler:
                st.error(f"⚠️ Aynı dosya birden fazla seçilmiş: **{', '.join(tekrar_edenler)}**\nLütfen tekrar eden dosyaları listeden kaldırın.")
                sinav_files = None
            else:
                sinav_files = sinav_files_raw
                s_imgs = [optimize_for_gemini(Image.open(f)) for f in sinav_files]
                st.session_state["sinav_img_map"] = {f.name: img for f, img in zip(sinav_files, s_imgs)}
                show_lightbox_gallery(s_imgs, "sinav")

    with col3:
        st.subheader("3. Ayarlar & Analiz")
        if "anahtar_metin" not in st.session_state: st.session_state["anahtar_metin"] = ""
        if "ana_talimat" not in st.session_state: st.session_state["ana_talimat"] = "Öğrenci kağıdını titizlikle oku. Okul No'yu ana referans al. Her soruyu puanla, kısmi puanlamaların nedenini kısaca belirt."

        if st.button("Cevap Anahtarını Oku", type="primary", use_container_width=True):
            if not cevap_files:
                st.warning("Cevap anahtarı yükleyin.")
            else:
                with st.spinner("Cevap Anahtarı okunuyor..."):
                    model = genai.GenerativeModel('gemini-3-flash-preview')
                    resp_c = model.generate_content(["Bu cevap anahtarını detaylıca oku ve kısmi puanlamalar belirgin olacak şekilde bir sınav okumasına referans olacak şekilde metne dök."] + c_imgs)
                    st.session_state["anahtar_metin"] = resp_c.text

        st.session_state["anahtar_metin"] = st.text_area("Cevap Anahtarı:", value=st.session_state["anahtar_metin"], height=200)
        st.session_state["ana_talimat"] = st.text_area("Ana Talimat:", value=st.session_state["ana_talimat"], height=100)

        if sinav_files:
            if st.button("Sınav Kağıtlarını Oku ve Analiz Et", type="primary", use_container_width=True):
                kredi = st.session_state.get("kredi", 0)
                sayfa_sayisi = len(sinav_files)
                if kredi < sayfa_sayisi:
                    st.error(f"❌ Yetersiz kredi! {sayfa_sayisi} sayfa için {sayfa_sayisi} kredi gerekli, krediniz: {kredi}")
                else:
                    st.session_state["start_analysis"] = True

        # --- Col3 içinde: progress ve durum bilgisi butonun altında ---
        progress_bar_ph = st.empty()
        sure_text_ph = st.empty()

    # --- Col3 dışında: canlı tablo tam genişlikte ---
    live_table_ph = st.empty()

    # --- Analiz bloğu ---
    if st.session_state.get("start_analysis") and sinav_files:
        st.session_state["start_analysis"] = False

        # Kredi düş
        sayfa_sayisi = len(sinav_files)
        db.collection("users").document(st.session_state["user_doc_id"]).update({
            "kredi": firestore.Increment(-sayfa_sayisi)
        })
        yeni_kredi = db.collection("users").document(st.session_state["user_doc_id"]).get().to_dict().get("kredi", 0)
        st.session_state["kredi"] = yeni_kredi

        
        baslangic_suresi = time.time()
        progress_bar = progress_bar_ph.progress(0)
        sure_text = sure_text_ph
        all_results = []
        basarisiz_dosyalar = []
        model = genai.GenerativeModel('gemini-3-flash-preview')

        def parse_gemini_response(resp_text):
            clean = resp_text.replace('```json', '').replace('```', '').strip()
            return json.loads(clean)

        for i, (f_name, s_img) in enumerate(zip([f.name for f in sinav_files], s_imgs)):
            sure_text.markdown(f"⏱️ **Geçen Süre:** {round(time.time() - baslangic_suresi, 1)} sn")

            prompt = (
                f"Talimat: {st.session_state['ana_talimat']}\n"
                f"Cevap Anahtarı: {st.session_state['anahtar_metin']}\n"
                f"⚠️ ÖNEMLİ: Sayfada fiziksel olarak GÖRÜNMEYEN soruları JSON'a EKLEME. Sadece bu sayfada gördüğün soruları ekle.\n"
                f"JSON döndür: {{\"sinif\": \"...\", \"okul_no\": \"...\", \"ad_soyad\": \"...\", \"sorular\": [ {{\"soru_no\": 1, \"puan\": 10, \"neden\": \"...\"}} ] }}"
            )

            data = None
            for deneme, bekleme in enumerate([0, 2, 5, 10]):
                if bekleme > 0:
                    sure_text.markdown(f"⏱️ **Geçen Süre:** {round(time.time() - baslangic_suresi, 1)} sn")
                    time.sleep(bekleme)
                try:
                    with col3:
                        with st.spinner(f"⌛ Okunan: {f_name} ({i+1}/{len(sinav_files)})"):
                            resp = model.generate_content([prompt, s_img])
                    data = parse_gemini_response(resp.text)
                    break
                except:
                    if deneme == 3:
                        basarisiz_dosyalar.append(f_name)

            #time.sleep(0.8)
            sure_text.markdown(f"⏱️ **Geçen Süre:** {round(time.time() - baslangic_suresi, 1)} sn")

            if data is not None:
                row = {
                    "Sınıf": data.get("sinif", ""),
                    "Okul No": str(data.get("okul_no", "")).strip(),
                    "Ad Soyad": str(data.get("ad_soyad", "")).strip().upper()
                }
                total = 0
                details = ""
                for s in data.get("sorular", []):
                    s_no = str(s.get('soru_no')).strip()
                    p_val = s.get('puan', 0)
                    row[f"Soru {s_no}"] = p_val
                    total += p_val
                    details += f"S{s_no}:{p_val}P - {s.get('neden', '')}|"
                row["Toplam"] = total
                row["Analiz Detay"] = details
                all_results.append(row)
                live_table_ph.dataframe(pd.DataFrame(all_results), use_container_width=True)

            progress_bar.progress((i + 1) / len(sinav_files))

        toplam_sure = round(time.time() - baslangic_suresi, 1)
        basarili = len(sinav_files) - len(basarisiz_dosyalar)
        sure_text.info(f"🏁 **Toplam Süre:** {toplam_sure} sn | ✅ {basarili}/{len(sinav_files)} kağıt okundu.")
        live_table_ph.empty()

        st.session_state["basarisiz_dosyalar"] = basarisiz_dosyalar
        st.session_state["full_data"] = pd.DataFrame(all_results)
        st.rerun()

    st.divider()

    # --- Okunamayan dosyalar uyarısı ve yeniden okuma butonu ---
    if st.session_state.get("basarisiz_dosyalar"):
        basarisiz = st.session_state["basarisiz_dosyalar"]
        st.warning(
            "⚠️ **Aşağıdaki sayfalar okunamadı** (Gemini 4 denemede de başarısız oldu). "
            "Bu öğrencilerin puanları eksik görünebilir:\n\n" +
            "\n".join(f"• `{f}`" for f in basarisiz)
        )
        if st.button("🔁 Okunamayan Sayfaları Yeniden Oku", type="primary", use_container_width=False):
            img_map = st.session_state.get("sinav_img_map", {})
            retry_files = [(f, img_map[f]) for f in basarisiz if f in img_map]
            if retry_files:
                model = genai.GenerativeModel('gemini-3-flash-preview')
                prompt = (
                    f"Talimat: {st.session_state['ana_talimat']}\n"
                    f"Cevap Anahtarı: {st.session_state['anahtar_metin']}\n"
                    f"⚠️ ÖNEMLİ: Sayfada fiziksel olarak GÖRÜNMEYEN soruları JSON'a EKLEME. Sadece bu sayfada gördüğün soruları ekle.\n"
                    f"JSON döndür: {{\"sinif\": \"...\", \"okul_no\": \"...\", \"ad_soyad\": \"...\", \"sorular\": [ {{\"soru_no\": 1, \"puan\": 10, \"neden\": \"...\"}} ] }}"
                )
                hala_basarisiz = []
                retry_bar = st.progress(0)
                retry_status = st.empty()
                for ri, (f_name, s_img) in enumerate(retry_files):
                    retry_status.write(f"🔁 Yeniden okunuyor: **{f_name}** ({ri+1}/{len(retry_files)})")
                    data = None
                    for deneme, bekleme in enumerate([0, 3, 8]):
                        if bekleme > 0: time.sleep(bekleme)
                        try:
                            with col3:
                                with st.spinner(f"⌛ Okunan: {f_name} ({ri+1}/{len(retry_files)})"):
                                    resp = model.generate_content([prompt, s_img])
                            clean = resp.text.replace('```json', '').replace('```', '').strip()
                            data = json.loads(clean)
                            break
                        except:
                            if deneme == 2: hala_basarisiz.append(f_name)
                    if data is not None:
                        row = {
                            "Sınıf": data.get("sinif", ""),
                            "Okul No": str(data.get("okul_no", "")).strip(),
                            "Ad Soyad": str(data.get("ad_soyad", "")).strip().upper()
                        }
                        total = 0
                        details = ""
                        for s in data.get("sorular", []):
                            s_no = str(s.get('soru_no')).strip()
                            p_val = s.get('puan', 0)
                            row[f"Soru {s_no}"] = p_val
                            total += p_val
                            details += f"S{s_no}:{p_val}P - {s.get('neden', '')}|"
                        row["Toplam"] = total
                        row["Analiz Detay"] = details
                        existing = st.session_state["full_data"]
                        st.session_state["full_data"] = pd.concat([existing, pd.DataFrame([row])], ignore_index=True)
                    retry_bar.progress((ri + 1) / len(retry_files))
                st.session_state["basarisiz_dosyalar"] = hala_basarisiz
                retry_status.success(f"✅ Yeniden okuma tamamlandı! {len(retry_files)-len(hala_basarisiz)}/{len(retry_files)} sayfa başarıyla okundu.")
                st.rerun()

    if "full_data" in st.session_state:
        st.subheader("📊 Sınav Sonuç Tablosu")
        df_full = st.session_state["full_data"]

        # --- SAYFA EŞLEŞTİRME ---
        id_map = {}
        for idx, row in df_full.iterrows():
            no = str(row['Okul No']).strip()
            ad = str(row['Ad Soyad']).upper().strip()
            isim_parca = ad.split()[0][:3] if ad else "ISIMSIZ"
            match_key = None
            if no and no != "None" and no != "":
                for k in id_map:
                    if k.split("_")[0] == no:
                        match_key = k
                        break
            if not match_key and ad:
                for k in id_map:
                    if isim_parca in k:
                        match_key = k
                        break
            if not match_key:
                match_key = f"{no}_{isim_parca}"
                id_map[match_key] = match_key
            df_full.at[idx, 'key'] = match_key

        s_cols = sorted(
            [c for c in df_full.columns if c.startswith('Soru') and 'Detay' not in c],
            key=lambda x: int(''.join(filter(str.isdigit, x))) if any(char.isdigit() for char in x) else 0
        )

        df_display = df_full.groupby('key', as_index=False).agg({
            'Sınıf': 'first', 'Okul No': 'first', 'Ad Soyad': 'first',
            **{c: 'max' for c in s_cols}
        })
        df_display[s_cols] = df_display[s_cols].apply(pd.to_numeric, errors='coerce').astype('Int64')
        df_display['Toplam'] = df_display[s_cols].fillna(0).sum(axis=1).astype(int)
        df_display = df_display[['Sınıf', 'Okul No', 'Ad Soyad'] + s_cols + ['Toplam']]

        st.dataframe(df_display, use_container_width=True)

        output = io.BytesIO()
        sinif_adi = str(df_display['Sınıf'].iloc[0]) if not df_display.empty else "Genel"

        # --- ANALİTİK RAPOR ---
        PLACEHOLDER_KEYWORDS = ["bulunmamaktadır", "yer almadığı", "yapılamamıştır",
                                 "görselde bulunmamaktadır", "sayfasında bulunmamaktadır"]

        def is_placeholder(text: str) -> bool:
            return any(kw in str(text) for kw in PLACEHOLDER_KEYWORDS)

        soru_sutunlari = sorted(
            [c for c in df_full.columns if c.startswith('Soru') and 'Detay' not in c],
            key=lambda x: int(''.join(filter(str.isdigit, x))) if any(ch.isdigit() for ch in x) else 0
        )

        a_rows = []
        for k, group in df_full.groupby('key'):
            toplam_puan = sum(
                group[c].fillna(0).max() for c in soru_sutunlari if c in group.columns
            )
            r = {
                'Sınıf': group['Sınıf'].iloc[0],
                'Okul No': group['Okul No'].iloc[0],
                'Ad Soyad': group['Ad Soyad'].iloc[0],
                'Toplam Puan': int(toplam_puan)
            }

            for s_col in soru_sutunlari:
                s_no_raw = s_col.replace('Soru ', '').strip()
                s_key = f"Soru {s_no_raw} Detay"
                best_detail = None
                best_score = -1

                for _, pg in group.iterrows():
                    score = pg.get(s_col, 0)
                    score = float(score) if pd.notna(score) else 0.0
                    detail_text = None
                    if 'Analiz Detay' in pg and pd.notna(pg['Analiz Detay']):
                        for part in str(pg['Analiz Detay']).split('|'):
                            part = part.strip()
                            if part and ':' in part:
                                bv = part.split(':', 1)
                                pno = bv[0].replace('S', '').strip()
                                if pno == s_no_raw:
                                    detail_text = bv[1].strip().replace('P -', ' Puan -')
                                    break
                    if detail_text is None:
                        continue
                    if score > best_score:
                        best_score = score
                        best_detail = detail_text
                    elif score == best_score and best_detail is not None:
                        if is_placeholder(best_detail) and not is_placeholder(detail_text):
                            best_detail = detail_text

                if best_detail is not None and not is_placeholder(best_detail):
                    r[s_key] = best_detail
                else:
                    sayfa_yuklendi = s_col in group.columns and group[s_col].notna().any()
                    r[s_key] = "Soru boş bırakılmıştır" if sayfa_yuklendi else "📄 Sayfa yüklenmedi"

            a_rows.append(r)

        df_analitik = pd.DataFrame(a_rows)
        d_cols = sorted(
            [c for c in df_analitik.columns if 'Detay' in c],
            key=lambda x: int(''.join(filter(str.isdigit, x))) if any(char.isdigit() for char in x) else 0
        )
        df_analitik = df_analitik[['Sınıf', 'Okul No', 'Ad Soyad'] + d_cols + ['Toplam Puan']]

        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df_display.to_excel(writer, sheet_name='Genel_Liste', index=False)
            df_display[['Sınıf', 'Okul No', 'Ad Soyad', 'Toplam']].to_excel(writer, sheet_name='e_Okul_Aktar', index=False)
            df_analitik.to_excel(writer, sheet_name='Analitik_Rapor', index=False)

            wb = writer.book
            h_fmt = wb.add_format({'bold': True, 'bg_color': '#bae6fd', 'border': 1, 'align': 'center', 'valign': 'vcenter'})
            c_center = wb.add_format({'border': 1, 'align': 'center', 'valign': 'vcenter'})
            c_left = wb.add_format({'border': 1, 'align': 'left', 'text_wrap': True, 'valign': 'vcenter'})
            toplam_fmt = wb.add_format({'bold': True, 'font_color': 'red', 'font_size': 14, 'border': 1, 'align': 'center', 'valign': 'vcenter'})
            soru_std_fmt = wb.add_format({'bold': True, 'border': 1, 'align': 'center', 'valign': 'vcenter'})
            rich_puan_fmt = wb.add_format({'bold': True, 'font_color': 'red', 'font_size': 12})

            for sn in writer.sheets:
                ws = writer.sheets[sn]
                cdf = df_display if sn == 'Genel_Liste' else (df_analitik if sn == 'Analitik_Rapor' else df_display[['Sınıf', 'Okul No', 'Ad Soyad', 'Toplam']])
                for c_idx, c_name in enumerate(cdf.columns):
                    ws.write(0, c_idx, c_name, h_fmt)
                    ws.set_column(c_idx, c_idx, 40 if 'Detay' in c_name else (25 if c_name == 'Ad Soyad' else 10))
                    for r_idx in range(1, len(cdf) + 1):
                        val = cdf.iloc[r_idx-1, c_idx]
                        fmt = c_center
                        if 'Toplam' in c_name: fmt = toplam_fmt
                        elif c_name.startswith('Soru ') and 'Detay' not in c_name: fmt = soru_std_fmt
                        elif 'Detay' in c_name or c_name == 'Ad Soyad': fmt = c_left
                        if pd.isna(val): ws.write_blank(r_idx, c_idx, None, fmt)
                        elif sn == 'Analitik_Rapor' and 'Detay' in c_name and 'Puan -' in str(val):
                            try:
                                pts = str(val).split('Puan -', 1)
                                ws.write_rich_string(r_idx, c_idx, rich_puan_fmt, pts[0] + "Puan", wb.add_format({'bold': False}), " -" + pts[1], fmt)
                            except:
                                ws.write(r_idx, c_idx, val, fmt)
                        else:
                            try:
                                ws.write(r_idx, c_idx, val, fmt)
                            except:
                                ws.write(r_idx, c_idx, str(val), fmt)

        st.download_button(
            label="📊 Detaylı Excel Raporunu İndir",
            data=output.getvalue(),
            file_name=f"{sinif_adi}_sinav_sonuclari.xlsx",
            type="primary",
            use_container_width=True
        )
else:
    st.info("Lütfen üstteki panelden giriş yapın.")
