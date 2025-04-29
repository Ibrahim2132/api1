import os
import json
import sys
from datetime import datetime, timedelta
import uuid
import io # <-- لإدارة البايتات
import hashlib # <-- لحساب الهاش

from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from dotenv import load_dotenv # <-- لتحميل متغيرات البيئة
from PIL import Image # <-- لمعالجة الصور
import google.generativeai as genai # <-- مكتبة Gemini

# --- Load Environment Variables ---
load_dotenv()
print("Attempting to load environment variables...") # Debug print

# --- تحديد المسارات ---

persistent_data_dir = '/tmp' # أو المسار المناسب لبيئتك
db_path = os.path.join(persistent_data_dir, 'databases4.db')
UPLOAD_FOLDER = os.path.join(persistent_data_dir, 'uploads')
db_dir = os.path.dirname(db_path) # مجلد قاعدة البيانات

# --- التأكد من وجود المجلدات الضرورية قبل إعداد التطبيق ---
# هذا مهم لأن SQLAlchemy قد يحاول إنشاء الملف مباشرة
try:
    print(f"Ensuring directory exists: {db_dir}")
    os.makedirs(db_dir, exist_ok=True) # تأكد من وجود مجلد قاعدة البيانات
    print(f"Ensuring directory exists: {UPLOAD_FOLDER}")
    os.makedirs(UPLOAD_FOLDER, exist_ok=True) # تأكد من وجود مجلد الرفع
    print("Required directories checked/created.")
except OSError as e:
    print(f"FATAL ERROR: Could not create necessary directories at {persistent_data_dir}. Check permissions/mount point. Error: {e}")
    # الخروج من البرنامج إذا لم نتمكن من إنشاء المجلدات الأساسية
    sys.exit(f"Directory creation failed: {e}")


# --- إعداد التطبيق و SQLAlchemy ---
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + db_path
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
# هام: أضف مفتاحًا سريًا! الأفضل تحميله من متغير بيئة
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'ضع-مفتاح-سري-قوي-هنا-للانتاج')
if app.config['SECRET_KEY'] == 'ضع-مفتاح-سري-قوي-هنا-للانتاج' and os.environ.get('FLASK_ENV') != 'development':
     print("WARNING: Using default SECRET_KEY in a non-development environment!")

db = SQLAlchemy(app)

# --- Configure Gemini API ---
GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY')
gemini_model = None # Initialize model as None

if not GOOGLE_API_KEY:
    print("ERROR: GOOGLE_API_KEY not found in environment variables (.env file). Image analysis will be disabled.")
else:
    try:
        print("Configuring Gemini API...")
        genai.configure(api_key=GOOGLE_API_KEY)
        # اختر الموديل المناسب - 'gemini-1.5-flash-latest' is a good balance
        gemini_model = genai.GenerativeModel('gemini-2.5-flash-preview-04-17')
        # يمكنك تجربة 'gemini-1.5-pro-latest' لدقة أعلى قد تكون مطلوبة
        # gemini_model = genai.GenerativeModel('gemini-1.5-pro-latest')
        print("Gemini Model configured successfully.")
    except Exception as e:
        print(f"ERROR configuring Gemini API: {e}. Image analysis will be disabled.")
        gemini_model = None # Keep model as None if configuration fails

# --- Define the Fixed Prompt for Like Detection ---
LIKE_DETECTION_PROMPT = """Analyze this social media screenshot. Focus ONLY on the primary like button/icon (e.g., heart, thumb up) associated with the main post content. Determine if this like button is in an 'activated' or 'liked' state. Respond with ONLY the single digit '1' if the post appears to be liked. Respond with ONLY the single digit '0' if the post appears to be *not* liked. Do not provide any other text, explanation, or formatting."""
COMMENT_DETECTION_PROMPT = """Analyze this social media screenshot (like TikTok, Instagram, Facebook). Search the visible comments section carefully for any comment posted by the username '{username}'. Pay close attention to the username associated with each comment. Respond with ONLY the single digit '1' if a comment clearly posted by the exact username '{username}' is visible in the screenshot. Respond with ONLY the single digit '0' if no comment by this exact username is clearly visible. Do not provide any other text, explanation, or formatting."""
SHARE_DETECTION_PROMPT = """Analyze this social media screenshot (like TikTok, Instagram, Facebook). Focus ONLY on the share button/icon (e.g., arrow, paper plane) or any text indicating a share action related to the main post. Determine if the post appears to have been shared by the user who took the screenshot (look for a highlighted or altered share icon, or text like 'Shared'). Respond with ONLY the single digit '1' if the post appears to have been shared. Respond with ONLY the single digit '0' if the post does not appear to have been shared. Do not provide any other text, explanation, or formatting."""
# --- END: Prompt جديد للمشاركة ---
# --- Storage for Processed Image Hashes (In-Memory) ---
# !!! هام: هذا الـ Set سيفقد محتوياته عند إعادة تشغيل السيرفر !!!
# للحل الدائم، استخدم قاعدة بيانات أو ملف لتخزين الـ Hashes.
processed_image_hashes = set()
print(f"Initialized empty set for processed image hashes. Size: {len(processed_image_hashes)}")


# --- تعريف موديل المستخدم (User Model) ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True) # البريد الإلكتروني فريد ومطلوب
    phone_number = db.Column(db.String(20), nullable=False) # رقم الهاتف مطلوب
    password_hash = db.Column(db.String(128), nullable=False) # تخزين هاش كلمة المرور
    interests = db.Column(db.Text, nullable=True) # الاهتمامات كقائمة نصية (JSON) (اختياري)

    # --- START: إضافة حقول الكوين والإحالة ---
    coins = db.Column(db.Integer, nullable=False, default=0) # عدد الكوينات، يبدأ بصفر
    referrer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, index=True) # ID الشخص الذي دعاه (اختياري)
    referred_by_me_ids = db.Column(db.Text, nullable=True) # IDs الأشخاص الذين دعاهم هذا المستخدم (JSON list)
    # --- END: إضافة حقول الكوين والإحالة ---
    last_spin_time = db.Column(db.DateTime, nullable=True) # وقت آخر مرة تم فيها تدوير العجلة بنجاح
    def set_password(self, password):
        """إنشاء هاش لكلمة المرور."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """التحقق من تطابق كلمة المرور المدخلة مع الهاش المخزن."""
        return check_password_hash(self.password_hash, password)

    # --- دوال الاهتمامات ---
    def set_interests(self, interests_list):
        """تحويل قائمة الاهتمامات إلى نص JSON لتخزينها."""
        if interests_list and isinstance(interests_list, list):
            if all(isinstance(item, str) for item in interests_list):
                self.interests = json.dumps(interests_list)
            else:
                app.logger.warning(f"User {self.id}: Interests list contains non-string elements. Setting interests to null.")
                self.interests = None
        else:
            self.interests = None

    def get_interests(self):
        """استرجاع قائمة الاهتمامات من نص JSON."""
        if self.interests:
            try:
                return json.loads(self.interests)
            except json.JSONDecodeError:
                app.logger.error(f"User {self.id}: Failed to decode interests JSON: {self.interests}")
                return []
        return []
    # --- نهاية دوال الاهتمامات ---

    # --- START: إضافة دوال لقائمة المدعوين ---
    def set_referred_by_me_ids(self, id_list):
        """تحويل قائمة IDs المدعوين إلى نص JSON لتخزينها."""
        if id_list and isinstance(id_list, list):
             # التأكد من أن كل عنصر في القائمة هو رقم صحيح
            if all(isinstance(item, int) for item in id_list):
                self.referred_by_me_ids = json.dumps(id_list)
            else:
                app.logger.warning(f"User {self.id}: referred_by_me_ids list contains non-integer elements. Setting to null.")
                self.referred_by_me_ids = None
        else:
            # إذا كانت القائمة فارغة أو غير صالحة، قم بتخزين قائمة فارغة أو null
            self.referred_by_me_ids = json.dumps([]) # الأفضل تخزين قائمة فارغة

    def get_referred_by_me_ids(self):
        """استرجاع قائمة IDs المدعوين من نص JSON."""
        if self.referred_by_me_ids:
            try:
                ids = json.loads(self.referred_by_me_ids)
                # تأكد من أن الناتج هو قائمة بالفعل
                return ids if isinstance(ids, list) else []
            except json.JSONDecodeError:
                app.logger.error(f"User {self.id}: Failed to decode referred_by_me_ids JSON: {self.referred_by_me_ids}")
                return [] # إرجاع قائمة فارغة في حالة الخطأ
        return []
    # --- END: إضافة دوال لقائمة المدعوين ---

    def to_dict(self):
        """إرجاع بيانات المستخدم كقاموس (بدون كلمة المرور)."""
        # جلب المستخدم الذي دعاه (إذا وجد)
        referrer_info = None
        if self.referrer_id:
            # تجنب استعلام آخر داخل to_dict إذا أمكن، لكن هنا ضروري إذا أردنا اسم الداعي
            # referrer_user = User.query.get(self.referrer_id)
            # if referrer_user:
            #     referrer_info = {"id": referrer_user.id, "name": referrer_user.name}
            # تبسيط: فقط أرجع الـ ID
             referrer_info = {"id": self.referrer_id}


        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "phone_number": self.phone_number,
            "interests": self.get_interests(), # استرجاع القائمة الفعلية
            # --- START: إضافة الحقول الجديدة للقاموس ---
            "coins": self.coins,
            "referrer": referrer_info, # معلومات الشخص الذي دعاه (أو null)
            "referred_by_me": self.get_referred_by_me_ids() # قائمة IDs الأشخاص الذين دعاهم
            # --- END: إضافة الحقول الجديدة للقاموس ---
        }

    def __repr__(self):
        """تمثيل نصي للمستخدم (مفيد للتصحيح)."""
        return f'<User {self.id} - {self.name} ({self.email}) - Coins: {self.coins}>'


# --- موديل الإعلانات (Advertisement Model) - بدون تغيير هنا ---
class Advertisement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True) # ربط الإعلان بالمستخدم
    title = db.Column(db.String(120), nullable=False) # عنوان الإعلان (إلزامي)
    description = db.Column(db.Text, nullable=True) # وصف الإعلان (اختياري)
    link = db.Column(db.Text, nullable=False) # رابط الإعلان (إلزامي)
    interests = db.Column(db.Text, nullable=True) # الاهتمامات كقائمة نصية (JSON) (اختياري)
    number_of_clicks = db.Column(db.Integer, nullable=False, default=0) # عدد النقرات (يبدأ بـ 0)
    coin_per_click = db.Column(db.Integer, nullable=False) # تكلفة النقرة بالعملات (إلزامي)
    category = db.Column(db.String(80), nullable=True, index=True) # الفئة (اختياري)
    subcategory = db.Column(db.String(80), nullable=True) # الفئة الفرعية (اختياري)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow) # تاريخ الإنشاء
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow) # تاريخ التحديث
    is_active = db.Column(db.Boolean, nullable=False, default=True) # هل الإعلان نشط؟
    is_approved = db.Column(db.Boolean, nullable=False, default=False, index=True) # هل تمت الموافقة على الإعلان؟ (افتراضي لا) - تمت إضافة index
    # images = db.Column(db.Text, nullable=True) # حقل للصور

    # دوال الاهتمامات للإعلانات
    def set_interests(self, interests_list):
        if interests_list and isinstance(interests_list, list):
            if all(isinstance(item, str) for item in interests_list):
                self.interests = json.dumps(interests_list)
            else:
                app.logger.warning(f"Ad {self.id}: Interests list contains non-string elements. Setting interests to null.")
                self.interests = None
        else:
            self.interests = None

    def get_interests(self):
        if self.interests:
            try:
                return json.loads(self.interests)
            except json.JSONDecodeError:
                app.logger.error(f"Ad {self.id}: Failed to decode interests JSON: {self.interests}")
                return []
        return []

    def to_dict(self):
        return {
            "id": self.id, "user_id": self.user_id, "title": self.title,
            "description": self.description, "link": self.link,
            "interests": self.get_interests(),
            "number_of_clicks": self.number_of_clicks, "coin_per_click": self.coin_per_click,
            "category": self.category, "subcategory": self.subcategory,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "is_active": self.is_active, "is_approved": self.is_approved,
            # "images": json.loads(self.images) if self.images else []
        }

    def __repr__(self):
        return f'<Advertisement {self.id} - {self.title}>'

# --- تهيئة قاعدة البيانات (إنشاء الجداول إذا لم تكن موجودة) ---
try:
    with app.app_context():
        print(f"Initializing database tables at: {db_path}...")
        # **هام:** إذا كنت لا تستخدم أداة ترحيل، قد تحتاج لحذف ملف .db القديم
        # عند إضافة أعمدة جديدة إلى موديل موجود.
        db.create_all()
        print("Database tables checked/created successfully.")
except Exception as e:
    print(f"FATAL ERROR during initial db.create_all(): {e}")
    sys.exit(f"Database initialization failed: {e}")


# --- دوال مساعدة وامتدادات مسموحة (بدون تغيير) ---
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# الدوال المساعدة _handle_image_upload و _save_entity تبقى كما هي (غير مستخدمة مباشرة في النقاط الرئيسية المعدلة)
def _handle_image_upload():
    # ... (الكود الأصلي هنا) ...
    pass # تبسيط للعرض

def _save_entity(entity, uploaded_filenames):
    # ... (الكود الأصلي هنا) ...
    pass # تبسيط للعرض


# --- نقطة نهاية التسجيل (معدلة لنظام الإحالة) ---
@app.route('/register', methods=['POST'])
def register():
    """نقطة نهاية لإنشاء مستخدم جديد مع دعم الإحالة."""
    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400

    data = request.get_json()
    name = data.get('name')
    email = data.get('email')
    password = data.get('password')
    phone_number = data.get('phone_number')
    interests_list = data.get('interests') # اختياري
    # --- START: استخراج referrer_id ---
    referrer_id_from_request = data.get('referrer_id') # اختياري
    # --- END: استخراج referrer_id ---

    # التحقق من وجود جميع الحقول المطلوبة
    missing_fields = []
    if not name: missing_fields.append('name')
    if not email: missing_fields.append('email')
    if not password: missing_fields.append('password')
    if not phone_number: missing_fields.append('phone_number')
    if missing_fields:
        return jsonify({"error": f"Missing required fields: {', '.join(missing_fields)}"}), 400

    # التحقق من أن البريد الإلكتروني غير مسجل مسبقًا
    if User.query.filter_by(email=email).first():
        return jsonify({"error": "Email address already registered"}), 409 # Conflict

    # التحقق من نوع الاهتمامات
    if interests_list is not None and not isinstance(interests_list, list):
        return jsonify({"error": "Field 'interests' must be a list of strings"}), 400
    if interests_list and not all(isinstance(item, str) for item in interests_list):
         return jsonify({"error": "All items in 'interests' list must be strings"}), 400

    # --- START: التحقق من الـ Referrer ---
    referrer = None
    valid_referrer_id = None
    if referrer_id_from_request is not None:
        # تأكد أنه رقم صحيح
        if not isinstance(referrer_id_from_request, int):
             return jsonify({"error": "Field 'referrer_id' must be an integer"}), 400

        # ابحث عن المستخدم الداعي
        referrer = User.query.get(referrer_id_from_request)
        if referrer is None:
            # إذا لم يتم العثور على الداعي، أرجع خطأ
            return jsonify({"error": f"Referrer user with ID {referrer_id_from_request} not found"}), 404 # أو 400 Bad Request
        else:
            valid_referrer_id = referrer.id # احتفظ بالـ ID الصحيح
            app.logger.info(f"Registration attempt with valid referrer: {valid_referrer_id}")
    # --- END: التحقق من الـ Referrer ---

    # إنشاء مستخدم جديد
    new_user = User(name=name, email=email, phone_number=phone_number)
    new_user.set_password(password)
    new_user.set_interests(interests_list)
    # --- START: تعيين referrer_id للمستخدم الجديد إذا كان صالحًا ---
    if valid_referrer_id:
        new_user.referrer_id = valid_referrer_id
    # --- END: تعيين referrer_id ---
    # ملاحظة: قيمة الكوينات الافتراضية (0) وقائمة المدعوين الفارغة يتم تعيينها بواسطة الـ default و set_referred_by_me_ids

    try:
        # الخطوة 1: إضافة المستخدم الجديد وحفظه للحصول على ID
        db.session.add(new_user)
        db.session.commit()
        app.logger.info(f"New user created with ID: {new_user.id}")

        # الخطوة 2: إذا كان هناك referrer صالح، قم بتحديثه
        if referrer: # استخدم الكائن الذي تم العثور عليه سابقًا
            try:
                # احصل على قائمة المدعوين الحالية للـ referrer
                referred_ids = referrer.get_referred_by_me_ids()
                # أضف الـ ID للمستخدم الجديد
                if new_user.id not in referred_ids: # تجنب الإضافة المكررة (احتياطي)
                    referred_ids.append(new_user.id)
                    referrer.set_referred_by_me_ids(referred_ids) # تحديث القائمة

                # زيادة الكوينات للـ referrer
                referrer.coins += 100
                app.logger.info(f"Awarding 100 coins to referrer {referrer.id}. New balance: {referrer.coins}")

                # حفظ التغييرات على الـ referrer
                db.session.commit()
                app.logger.info(f"Referrer {referrer.id} updated successfully.")

            except Exception as e_ref:
                # إذا فشل تحديث الـ referrer، يجب تسجيل الخطأ ولكن *لا تقم* بإلغاء تسجيل المستخدم الجديد
                # قد ترغب في إضافة آلية لإعادة المحاولة لاحقًا
                db.session.rollback() # التراجع عن تغييرات الـ referrer فقط
                app.logger.error(f"ERROR updating referrer {referrer.id} for new user {new_user.id}: {e_ref}", exc_info=True)
                # لا ترجع خطأ 500 هنا، استمر في إرجاع نجاح تسجيل المستخدم

        # إرجاع بيانات المستخدم الجديد
        return jsonify({
            "message": "User registered successfully!",
            # new_user تم تحديثه بالـ ID بعد الـ commit الأول
            "user": new_user.to_dict() # سيحتوي الآن على الكوينات و referrer_id إذا كان موجودًا
        }), 201 # Created

    except Exception as e_reg:
        db.session.rollback() # التراجع عن إضافة المستخدم الجديد
        app.logger.error(f"Registration Error: {e_reg}", exc_info=True)
        return jsonify({"error": "Internal Server Error during registration"}), 500


# --- نقطة نهاية تسجيل الدخول (بدون تغيير جوهري، فقط الـ to_dict سيعيد بيانات أكثر) ---
@app.route('/login', methods=['POST'])
def login():
    """نقطة نهاية لتسجيل دخول المستخدم."""
    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400

    data = request.get_json()
    email = data.get('email')
    password = data.get('password')

    if not email or not password:
        return jsonify({"error": "Missing email or password"}), 400

    user = User.query.filter_by(email=email).first()

    if user is None or not user.check_password(password):
        return jsonify({"error": "Invalid email or password"}), 401 # Unauthorized

    # تسجيل الدخول ناجح، إرجاع بيانات المستخدم المحدثة
    return jsonify({
        "message": "Login successful!",
        "user": user.to_dict() # ستشمل الآن الكوينات ومعلومات الإحالة
    }), 200 # OK
@app.route('/users/<int:user_id>/spin_wheel', methods=['POST'])
def spin_wheel(user_id):
    """محاولة تدوير عجلة الحظ اليومية للمستخدم."""
    user = User.query.get(user_id)
    if user is None:
        return jsonify({"error": f"User with ID {user_id} not found"}), 404

    now = datetime.utcnow()
    cooldown_period = timedelta(hours=24) # فترة الانتظار 24 ساعة
    # --- حساب الوقت المتبقي (بشكل أدق) ---
    remaining_time_str = ""
    remaining_seconds = 0
    can_spin = False

    if user.last_spin_time is None:
        # أول مرة يدور العجلة
        can_spin = True
        app.logger.info(f"User {user_id} spinning for the first time.")
    else:
        time_since_last_spin = now - user.last_spin_time
        if time_since_last_spin >= cooldown_period:
            # مر وقت كافٍ
            can_spin = True
            app.logger.info(f"User {user_id} eligible to spin again. Last spin was {time_since_last_spin.total_seconds():.0f}s ago.")
        else:
            # لم يمر وقت كافٍ
            remaining_time = cooldown_period - time_since_last_spin
            remaining_seconds = int(remaining_time.total_seconds())
            # تحويل الثواني المتبقية إلى ساعات ودقائق وثواني للقراءة
            hours, remainder = divmod(remaining_seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            remaining_time_str = f"{hours}h {minutes}m {seconds}s"
            app.logger.info(f"User {user_id} tried to spin too early. Remaining time: {remaining_time_str}")

    if can_spin:
        try:
            # *** هنا يمكنك إضافة منطق تحديد الجائزة الفعلية (مثلاً عدد عشوائي من الكوينات) ***
            # prize_coins = random.randint(10, 50) # مثال: ربح عدد عشوائي من الكوينات
            # user.coins += prize_coins

            # تحديث وقت آخر تدوير ناجح
            user.last_spin_time = now
            db.session.commit()

            app.logger.info(f"User {user_id} spin successful. Last spin time updated to {now.isoformat()}")
            return jsonify({
                "status": 1,
                "message": "Spin successful! You can spin again in 24 hours.",
                # "prize": prize_coins # مثال: إرجاع قيمة الجائزة
                "new_coins_balance": user.coins # إرجاع رصيد الكوينات المحدث (إذا تم تغييرها)
            }), 200
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Error during successful spin commit for user {user_id}: {e}", exc_info=True)
            return jsonify({"error": "Internal server error processing spin"}), 500
    else:
        # إرجاع حالة الفشل مع الوقت المتبقي
        return jsonify({
            "status": 0,
            "message": f"Please wait. Time remaining: {remaining_time_str}",
            "remaining_seconds": remaining_seconds # إرجاع الثواني المتبقية قد يكون مفيدًا للـ frontend
        }), 200 # نستخدم 200 OK حتى لو فشلت المحاولة، لكن status: 0 يوضح ذلك

# --- END: نقطة نهاية جديدة لعجلة الحظ ---


# --- نقطة نهاية جلب المستخدم بالـ ID (بدون تغيير جوهري) ---
@app.route('/users/<int:user_id>', methods=['GET'])
def get_user_by_id(user_id):
    """نقطة نهاية لجلب بيانات مستخدم معين بواسطة ID."""
    user = User.query.get(user_id)

    if user is None:
        return jsonify({"error": f"User with ID {user_id} not found"}), 404

    return jsonify(user.to_dict()), 200 # OK


# --- نقطة نهاية تحديث اهتمامات المستخدم (بدون تغيير) ---
@app.route('/users/<int:user_id>/interests', methods=['PUT'])
def update_user_interests(user_id):
     # ... (الكود الأصلي هنا) ...
    if not request.is_json: return jsonify({"error": "Request must be JSON"}), 400
    user = User.query.get(user_id)
    if user is None: return jsonify({"error": f"User with ID {user_id} not found"}), 404
    data = request.get_json()
    interests_list = data.get('interests')
    if interests_list is None: return jsonify({"error": "Missing 'interests' field"}), 400
    if not isinstance(interests_list, list) or not all(isinstance(i, str) for i in interests_list):
        return jsonify({"error": "'interests' must be a list of strings"}), 400
    try:
        user.set_interests(interests_list)
        db.session.commit()
        return jsonify({"message": "Interests updated", "user": user.to_dict()}), 200
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error updating interests for user {user_id}: {e}", exc_info=True)
        return jsonify({"error": "Internal Server Error"}), 500


# --- نقاط نهاية الإعلانات (بدون تغيير) ---
@app.route('/add_advertisement', methods=['POST'])
def add_advertisement():
    # ... (الكود الأصلي هنا) ...
    if not request.is_json: return jsonify({"error": "Request must be JSON"}), 400
    data = request.get_json()
    # ... (بقية التحققات والإنشاء كما في الكود الأصلي) ...
    user_id = data.get('user_id')
    user = User.query.get(user_id)
    if not user: return jsonify({"error": f"User {user_id} not found"}), 404
    # ... إنشاء new_ad وتعيين الحقول ...
    new_ad = Advertisement(
        user_id=user_id, title=data.get('title'), link=data.get('link'),
        coin_per_click=data.get('coin_per_click'), description=data.get('description'),
        category=data.get('category'), subcategory=data.get('subcategory')
    )
    interests_list = data.get('interests')
    if interests_list: new_ad.set_interests(interests_list)
    # التحقق من الحقول الإلزامية الأخرى...
    if not all([new_ad.title, new_ad.link, new_ad.coin_per_click is not None]):
         return jsonify({"error": "Missing required fields for advertisement"}), 400
    if not isinstance(new_ad.coin_per_click, int) or new_ad.coin_per_click < 0:
         return jsonify({"error": "'coin_per_click' must be non-negative integer"}), 400

    try:
        db.session.add(new_ad)
        db.session.commit()
        return jsonify({"message": "Advertisement submitted", "advertisement": new_ad.to_dict()}), 201
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error creating ad for user {user_id}: {e}", exc_info=True)
        return jsonify({"error": "Internal Server Error"}), 500


@app.route('/admin/advertisements/<int:ad_id>/approve', methods=['PUT'])
def approve_advertisement(ad_id):
    # ... (الكود الأصلي هنا، مع الحماية اللازمة للأدمن) ...
    # يجب إضافة تحقق من أن المستخدم الذي يستدعي هذه النقطة هو أدمن
    advertisement = Advertisement.query.get(ad_id)
    if advertisement is None: return jsonify({"error": "Ad not found"}), 404
    if advertisement.is_approved: return jsonify({"message": "Already approved", "advertisement": advertisement.to_dict()}), 200
    try:
        advertisement.is_approved = True
        advertisement.updated_at = datetime.utcnow()
        db.session.commit()
        return jsonify({"message": "Advertisement approved", "advertisement": advertisement.to_dict()}), 200
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error approving ad {ad_id}: {e}", exc_info=True)
        return jsonify({"error": "Internal Server Error"}), 500


@app.route('/advertisements', methods=['GET'])
def get_all_advertisements():
    # ... (الكود الأصلي هنا) ...
    all_ads = Advertisement.query.order_by(Advertisement.created_at.desc()).all()
    return jsonify([ad.to_dict() for ad in all_ads]), 200


@app.route('/advertisements/approved', methods=['GET'])
def get_approved_advertisements():
    # ... (الكود الأصلي هنا) ...
    approved_ads = Advertisement.query.filter_by(is_approved=True, is_active=True)\
                                      .order_by(Advertisement.created_at.desc()).all()
    return jsonify([ad.to_dict() for ad in approved_ads]), 200
@app.route('/analyze_like_status', methods=['POST'])
def analyze_like_status():
    """تحليل صورة لتحديد حالة الإعجاب والتحقق من التكرار."""
    if not gemini_model:
        app.logger.error("analyze_like_status endpoint called but Gemini model is not configured.")
        return jsonify({"error": "Image analysis service is currently unavailable."}), 503 # Service Unavailable

    # 1. التحقق من وجود ملف الصورة في الطلب
    if 'image' not in request.files:
        return jsonify({"error": "Missing 'image' file part in the request."}), 400

    file = request.files['image']

    # 2. التحقق من أن اسم الملف ليس فارغًا (اختياري لكن جيد)
    if file.filename == '':
        return jsonify({"error": "No file selected."}), 400

    # 3. قراءة بايتات الصورة وحساب الهاش
    try:
        img_bytes = file.read()
        if not img_bytes:
             return jsonify({"error": "Empty image file received."}), 400

        # استخدم SHA256 لأنه أكثر أمانًا من MD5
        img_hash = hashlib.sha256(img_bytes).hexdigest()
        app.logger.debug(f"Calculated hash for uploaded image: {img_hash}")

    except Exception as e:
        app.logger.error(f"Error reading or hashing image file: {e}", exc_info=True)
        return jsonify({"error": "Could not process image file."}), 400

    # 4. التحقق من تكرار الصورة
    if img_hash in processed_image_hashes:
        app.logger.warning(f"Duplicate image detected with hash: {img_hash}")
        return jsonify({
            "status": -1, # استخدام -1 للإشارة إلى التكرار
            "message": "Image already processed."
        }), 200 # OK، لكن الـ status يوضح التكرار

    app.logger.info(f"Processing new image with hash: {img_hash}")

    # 5. محاولة فتح الصورة باستخدام Pillow للتحقق من صلاحيتها قبل إرسالها
    try:
        img = Image.open(io.BytesIO(img_bytes))
        # يمكنك إضافة تحققات أخرى هنا (مثل الأبعاد، النوع) إذا لزم الأمر
        img.verify() # محاولة بسيطة للتحقق من أن الملف ليس تالفًا تمامًا
        # إعادة فتح الصورة بعد verify لأن verify تستهلك stream
        img = Image.open(io.BytesIO(img_bytes))
        print(f"Image verified and re-opened successfully (format: {img.format}).") # Debug print

    except Exception as e:
        app.logger.error(f"Invalid or corrupted image file for hash {img_hash}: {e}", exc_info=True)
        # لا نضيف الهاش للـ set إذا كانت الصورة تالفة
        return jsonify({"error": "Invalid or corrupted image file."}), 400

    # 6. إرسال الصورة إلى Gemini للتحليل
    try:
        app.logger.info(f"Sending image {img_hash} to Gemini for like detection...")
        response = gemini_model.generate_content([LIKE_DETECTION_PROMPT, img])

        # 7. معالجة استجابة Gemini
        if response.parts:
            raw_result = response.text.strip()
            app.logger.info(f"Raw Gemini response for hash {img_hash}: '{raw_result}'")

            if raw_result == "1":
                # نجاح - الصورة معلمة كـ "معجب به"
                processed_image_hashes.add(img_hash) # إضافة الهاش بعد النجاح
                app.logger.info(f"Hash {img_hash} added to processed set. Current set size: {len(processed_image_hashes)}")
                return jsonify({"status": 1, "message": "Image indicates liked status."}), 200
            elif raw_result == "0":
                # نجاح - الصورة معلمة كـ "غير معجب به"
                processed_image_hashes.add(img_hash) # إضافة الهاش بعد النجاح
                app.logger.info(f"Hash {img_hash} added to processed set. Current set size: {len(processed_image_hashes)}")
                return jsonify({"status": 0, "message": "Image indicates not liked status."}), 200
            else:
                # استجابة غير متوقعة من Gemini
                app.logger.error(f"Unexpected Gemini response for hash {img_hash}: '{raw_result}'. Expected '1' or '0'.")
                # لا نضيف الهاش في هذه الحالة لأن التحليل لم يكن حاسمًا
                return jsonify({"error": f"Analysis returned unexpected result: '{raw_result}'"}), 500 # خطأ في الخادم لأن الاستجابة غير متوقعة
        else:
            # لم ترجع Gemini محتوى (قد يكون بسبب فلاتر الأمان)
            feedback = response.prompt_feedback if hasattr(response, 'prompt_feedback') else 'N/A'
            app.logger.error(f"Gemini returned no content for hash {img_hash}. Feedback: {feedback}")
            # لا نضيف الهاش
            return jsonify({"error": "Analysis failed or content blocked by safety filters."}), 500

    except Exception as e:
        app.logger.error(f"Error calling Gemini API for hash {img_hash}: {e}", exc_info=True)
        # لا نضيف الهاش
        return jsonify({"error": f"An error occurred during image analysis: {str(e)}"}), 500 # خطأ عام في الخادم
@app.route('/analyze_comment_status', methods=['POST'])
def analyze_comment_status():
    """تحليل صورة للبحث عن تعليق من مستخدم معين والتحقق من تكرار الصورة."""
    if not gemini_model:
        app.logger.error("analyze_comment_status endpoint called but Gemini model is not configured.")
        return jsonify({"error": "Image analysis service is currently unavailable."}), 503

    # 1. التحقق من وجود البيانات المطلوبة (صورة واسم مستخدم)
    if 'image' not in request.files:
        return jsonify({"error": "Missing 'image' file part in the request."}), 400
    if 'username' not in request.form:
        return jsonify({"error": "Missing 'username' form field in the request."}), 400

    file = request.files['image']
    username = request.form['username'] # احصل على اسم المستخدم من الـ form data

    # 2. التحقق من أن اسم المستخدم ليس فارغًا
    if not username:
        return jsonify({"error": "'username' cannot be empty."}), 400

    # 3. التحقق من أن اسم الملف ليس فارغًا
    if file.filename == '':
        return jsonify({"error": "No image file selected."}), 400

    # 4. قراءة بايتات الصورة وحساب الهاش (نفس كود تحليل الإعجاب)
    try:
        img_bytes = file.read()
        if not img_bytes:
             return jsonify({"error": "Empty image file received."}), 400
        img_hash = hashlib.sha256(img_bytes).hexdigest()
        app.logger.debug(f"Calculated hash for comment analysis image: {img_hash}")
    except Exception as e:
        app.logger.error(f"Error reading or hashing image file for comment analysis: {e}", exc_info=True)
        return jsonify({"error": "Could not process image file."}), 400

    # 5. التحقق من تكرار الصورة (نفس كود تحليل الإعجاب)
    if img_hash in processed_image_hashes:
        app.logger.warning(f"Duplicate image detected for comment analysis with hash: {img_hash}")
        # حتى لو الصورة مكررة، قد يكون المستخدم يبحث عن username مختلف،
        # لكن منطق السؤال هو "هل الصورة مكررة"، لذا نرجع -1
        return jsonify({
            "status": -1,
            "message": "Image already processed (for like or comment)."
        }), 200

    app.logger.info(f"Processing new image for comment analysis. Hash: {img_hash}, Username: '{username}'")

    # 6. محاولة فتح الصورة والتحقق منها (نفس كود تحليل الإعجاب)
    try:
        img = Image.open(io.BytesIO(img_bytes))
        img.verify()
        img = Image.open(io.BytesIO(img_bytes)) # Re-open
        print(f"Comment image verified and re-opened successfully (format: {img.format}).")
    except Exception as e:
        app.logger.error(f"Invalid or corrupted image file for comment analysis {img_hash}: {e}", exc_info=True)
        return jsonify({"error": "Invalid or corrupted image file."}), 400

    # 7. إرسال الصورة والـ Prompt الخاص بالتعليقات إلى Gemini
    try:
        # قم بتضمين اسم المستخدم في الـ Prompt
        comment_prompt = COMMENT_DETECTION_PROMPT.format(username=username)
        app.logger.info(f"Sending image {img_hash} to Gemini for comment detection (user: '{username}').")
        # تأكد من تمرير الـ Prompt الجديد
        response = gemini_model.generate_content([comment_prompt, img])

        # 8. معالجة استجابة Gemini
        if response.parts:
            raw_result = response.text.strip()
            app.logger.info(f"Raw Gemini comment response for hash {img_hash} (user: '{username}'): '{raw_result}'")

            if raw_result == "1":
                # نجاح - تم العثور على تعليق للمستخدم
                processed_image_hashes.add(img_hash) # أضف الهاش
                app.logger.info(f"Comment found. Hash {img_hash} added to processed set. Size: {len(processed_image_hashes)}")
                return jsonify({"status": 1, "message": f"Comment found for username '{username}'."}), 200
            elif raw_result == "0":
                # نجاح - لم يتم العثور على تعليق للمستخدم
                processed_image_hashes.add(img_hash) # أضف الهاش
                app.logger.info(f"Comment not found. Hash {img_hash} added to processed set. Size: {len(processed_image_hashes)}")
                return jsonify({"status": 0, "message": f"Comment not found for username '{username}'."}), 200
            else:
                # استجابة غير متوقعة
                app.logger.error(f"Unexpected Gemini comment response for hash {img_hash} (user: '{username}'): '{raw_result}'.")
                return jsonify({"error": f"Analysis returned unexpected result: '{raw_result}'"}), 500
        else:
            # لا يوجد محتوى (ربما فلاتر الأمان)
            feedback = response.prompt_feedback if hasattr(response, 'prompt_feedback') else 'N/A'
            app.logger.error(f"Gemini returned no content for comment analysis {img_hash} (user: '{username}'). Feedback: {feedback}")
            return jsonify({"error": "Comment analysis failed or content blocked by safety filters."}), 500

    except Exception as e:
        app.logger.error(f"Error calling Gemini API for comment analysis {img_hash} (user: '{username}'): {e}", exc_info=True)
        return jsonify({"error": f"An error occurred during comment analysis: {str(e)}"}), 500

@app.route('/analyze_share_status', methods=['POST'])
def analyze_share_status():
    """تحليل صورة لتحديد حالة المشاركة والتحقق من التكرار."""
    if not gemini_model:
        app.logger.error("analyze_share_status endpoint called but Gemini model is not configured.")
        return jsonify({"error": "Image analysis service is currently unavailable."}), 503

    # 1. التحقق من وجود ملف الصورة
    if 'image' not in request.files:
        return jsonify({"error": "Missing 'image' file part in the request."}), 400

    file = request.files['image']

    # 2. التحقق من اسم الملف
    if file.filename == '':
        return jsonify({"error": "No file selected."}), 400

    # 3. قراءة البايتات وحساب الهاش
    try:
        img_bytes = file.read()
        if not img_bytes:
             return jsonify({"error": "Empty image file received."}), 400
        img_hash = hashlib.sha256(img_bytes).hexdigest()
        app.logger.debug(f"Calculated hash for share analysis image: {img_hash}")
    except Exception as e:
        app.logger.error(f"Error reading or hashing image file for share analysis: {e}", exc_info=True)
        return jsonify({"error": "Could not process image file."}), 400

    # 4. التحقق من التكرار
    if img_hash in processed_image_hashes:
        app.logger.warning(f"Duplicate image detected for share analysis with hash: {img_hash}")
        return jsonify({
            "status": -1,
            "message": "Image already processed (for like, comment, or share)." # تعديل الرسالة قليلاً
        }), 200

    app.logger.info(f"Processing new image for share analysis. Hash: {img_hash}")

    # 5. التحقق من صحة الصورة
    try:
        img = Image.open(io.BytesIO(img_bytes))
        img.verify()
        img = Image.open(io.BytesIO(img_bytes)) # Re-open
        print(f"Share image verified and re-opened successfully (format: {img.format}).")
    except Exception as e:
        app.logger.error(f"Invalid or corrupted image file for share analysis {img_hash}: {e}", exc_info=True)
        return jsonify({"error": "Invalid or corrupted image file."}), 400

    # 6. إرسال الصورة والـ Prompt الخاص بالمشاركة إلى Gemini
    try:
        app.logger.info(f"Sending image {img_hash} to Gemini for share detection...")
        # استخدم الـ Prompt الجديد
        response = gemini_model.generate_content([SHARE_DETECTION_PROMPT, img])

        # 7. معالجة استجابة Gemini
        if response.parts:
            raw_result = response.text.strip()
            app.logger.info(f"Raw Gemini share response for hash {img_hash}: '{raw_result}'")

            if raw_result == "1":
                # نجاح - تم العثور على مؤشر مشاركة
                processed_image_hashes.add(img_hash)
                app.logger.info(f"Share detected. Hash {img_hash} added to processed set. Size: {len(processed_image_hashes)}")
                return jsonify({"status": 1, "message": "Image indicates shared status."}), 200
            elif raw_result == "0":
                # نجاح - لم يتم العثور على مؤشر مشاركة
                processed_image_hashes.add(img_hash)
                app.logger.info(f"Share not detected. Hash {img_hash} added to processed set. Size: {len(processed_image_hashes)}")
                return jsonify({"status": 0, "message": "Image indicates not shared status."}), 200
            else:
                # استجابة غير متوقعة
                app.logger.error(f"Unexpected Gemini share response for hash {img_hash}: '{raw_result}'.")
                return jsonify({"error": f"Analysis returned unexpected result: '{raw_result}'"}), 500
        else:
            # لا يوجد محتوى
            feedback = response.prompt_feedback if hasattr(response, 'prompt_feedback') else 'N/A'
            app.logger.error(f"Gemini returned no content for share analysis {img_hash}. Feedback: {feedback}")
            return jsonify({"error": "Share analysis failed or content blocked by safety filters."}), 500

    except Exception as e:
        app.logger.error(f"Error calling Gemini API for share analysis {img_hash}: {e}", exc_info=True)
        return jsonify({"error": f"An error occurred during share analysis: {str(e)}"}), 500

@app.route('/users/<int:user_id>', methods=['PATCH'])
def update_user_data(user_id):
    """تحديث بيانات مستخدم معين (الاسم، الهاتف، الاهتمامات، إضافة/طرح كوينز)."""
    user = User.query.get(user_id)
    if user is None:
        return jsonify({"error": f"User with ID {user_id} not found"}), 404

    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400

    data = request.get_json()
    if not data:
        return jsonify({"error": "Request body cannot be empty for update"}), 400

    updated_fields = [] # لتتبع الحقول التي تم تحديثها

    # تحديث الاسم
    if 'name' in data:
        new_name = data['name']
        if isinstance(new_name, str) and new_name.strip():
            user.name = new_name.strip()
            updated_fields.append('name')
            app.logger.info(f"User {user_id}: Name updated.")
        else:
            return jsonify({"error": "Invalid value for 'name'. Must be a non-empty string."}), 400

    # تحديث رقم الهاتف
    if 'phone_number' in data:
        new_phone = data['phone_number']
        # يمكنك إضافة تحقق أكثر تفصيلاً من صيغة الرقم هنا
        if isinstance(new_phone, str) and new_phone.strip():
            user.phone_number = new_phone.strip()
            updated_fields.append('phone_number')
            app.logger.info(f"User {user_id}: Phone number updated.")
        else:
            return jsonify({"error": "Invalid value for 'phone_number'. Must be a non-empty string."}), 400

    # تحديث الاهتمامات
    if 'interests' in data:
        interests_list = data['interests']
        if interests_list is None or (isinstance(interests_list, list) and all(isinstance(i, str) for i in interests_list)):
            user.set_interests(interests_list) # الدالة تعالج None أو القائمة الصحيحة
            updated_fields.append('interests')
            app.logger.info(f"User {user_id}: Interests updated.")
        else:
             return jsonify({"error": "'interests' must be a list of strings or null."}), 400

    # تحديث الكوينز (إضافة/طرح)
    coins_changed = False
    if 'add_coins' in data:
        try:
            amount_to_add = int(data['add_coins'])
            if amount_to_add < 0:
                 return jsonify({"error": "'add_coins' must be a non-negative integer."}), 400
            user.coins += amount_to_add
            coins_changed = True
            app.logger.info(f"User {user_id}: Added {amount_to_add} coins. New balance: {user.coins}")
        except (ValueError, TypeError):
            return jsonify({"error": "'add_coins' must be an integer."}), 400

    if 'subtract_coins' in data:
        try:
            amount_to_subtract = int(data['subtract_coins'])
            if amount_to_subtract < 0:
                 return jsonify({"error": "'subtract_coins' must be a non-negative integer."}), 400
            if user.coins >= amount_to_subtract:
                user.coins -= amount_to_subtract
            else:
                # منع الرصيد السالب، يمكنك إرجاع خطأ أو تصفير الرصيد
                app.logger.warning(f"User {user_id}: Tried to subtract {amount_to_subtract} coins, but only had {user.coins}. Setting coins to 0.")
                user.coins = 0 # تصفير الرصيد
                # أو يمكنك إرجاع خطأ:
                # return jsonify({"error": f"Insufficient coins. Cannot subtract {amount_to_subtract}."}), 400
            coins_changed = True
            app.logger.info(f"User {user_id}: Subtracted {amount_to_subtract} coins. New balance: {user.coins}")
        except (ValueError, TypeError):
             return jsonify({"error": "'subtract_coins' must be an integer."}), 400

    if coins_changed:
        updated_fields.append('coins')

    # التحقق إذا تم تحديث أي شيء
    if not updated_fields:
        return jsonify({"message": "No valid fields provided for update."}), 200 # أو 304 Not Modified

    # حفظ التغييرات
    try:
        db.session.commit()
        app.logger.info(f"User {user_id}: Successfully updated fields: {', '.join(updated_fields)}")
        return jsonify({
            "message": f"User data updated successfully ({', '.join(updated_fields)}).",
            "user": user.to_dict() # إرجاع بيانات المستخدم المحدثة
        }), 200
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error committing updates for user {user_id}: {e}", exc_info=True)
        return jsonify({"error": "Internal Server Error during update."}), 500

# --- التشغيل المحلي (بدون تغيير) ---
if __name__ == '__main__':
    print("Starting Flask development server (for local testing)...")
    # تذكر: احذف ملف .db إذا غيرت الـ model ولم تستخدم migrations
    app.run(debug=True, host='0.0.0.0', port=5000)

# --- END OF MODIFIED FILE app.py ---
