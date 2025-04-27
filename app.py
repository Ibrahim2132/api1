# --- START OF MODIFIED FILE app.py ---
import os
import json
import sys # استيراد sys للخروج عند الخطأ إذا لزم الأمر
from datetime import datetime # <-- إضافة لاستخدام الطوابع الزمنية
import uuid
import sys # استيراد sys للخروج عند الخطأ إذا لزم الأمر
from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

# --- تحديد المسارات ---

persistent_data_dir = '/tmp'
db_path = os.path.join(persistent_data_dir, 'databases1.db')
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


# --- تعريف موديل المستخدم (User Model) ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True) # البريد الإلكتروني فريد ومطلوب
    phone_number = db.Column(db.String(20), nullable=False) # رقم الهاتف مطلوب
    password_hash = db.Column(db.String(128), nullable=False) # تخزين هاش كلمة المرور
    # --- START: إضافة حقل الاهتمامات ---
    interests = db.Column(db.Text, nullable=True) # الاهتمامات كقائمة نصية (JSON) (اختياري)
    # --- END: إضافة حقل الاهتمامات ---

    def set_password(self, password):
        """إنشاء هاش لكلمة المرور."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """التحقق من تطابق كلمة المرور المدخلة مع الهاش المخزن."""
        return check_password_hash(self.password_hash, password)

    # --- START: إضافة دوال للاهتمامات ---
    def set_interests(self, interests_list):
        """تحويل قائمة الاهتمامات إلى نص JSON لتخزينها."""
        if interests_list and isinstance(interests_list, list):
            # التأكد من أن كل عنصر في القائمة هو نص
            if all(isinstance(item, str) for item in interests_list):
                self.interests = json.dumps(interests_list)
            else:
                # يمكنك رفع خطأ هنا أو تسجيل تحذير
                app.logger.warning(f"User {self.id}: Interests list contains non-string elements. Setting interests to null.")
                self.interests = None # أو json.dumps([])
        else:
            self.interests = None # أو json.dumps([])

    def get_interests(self):
        """استرجاع قائمة الاهتمامات من نص JSON."""
        if self.interests:
            try:
                return json.loads(self.interests)
            except json.JSONDecodeError:
                app.logger.error(f"User {self.id}: Failed to decode interests JSON: {self.interests}")
                return [] # إرجاع قائمة فارغة في حالة الخطأ
        return []
    # --- END: إضافة دوال للاهتمامات ---

    def to_dict(self):
        """إرجاع بيانات المستخدم كقاموس (بدون كلمة المرور)."""
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "phone_number": self.phone_number,
            # --- START: إضافة الاهتمامات إلى القاموس ---
            "interests": self.get_interests() # استرجاع القائمة الفعلية
            # --- END: إضافة الاهتمامات إلى القاموس ---
        }

    def __repr__(self):
        """تمثيل نصي للمستخدم (مفيد للتصحيح)."""
        return f'<User {self.name} - {self.email}>'

class Advertisement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True) # ربط الإعلان بالمستخدم
    title = db.Column(db.String(120), nullable=False) # عنوان الإعلان (إلزامي)
    description = db.Column(db.Text, nullable=True) # وصف الإعلان (اختياري)
    link = db.Column(db.Text, nullable=False) # رابط الإعلان (إلزامي)
    # --- START: إضافة حقل الاهتمامات ---
    interests = db.Column(db.Text, nullable=True) # الاهتمامات كقائمة نصية (JSON) (اختياري)
    # --- END: إضافة حقل الاهتمامات ---
    number_of_clicks = db.Column(db.Integer, nullable=False, default=0) # عدد النقرات (يبدأ بـ 0)
    coin_per_click = db.Column(db.Integer, nullable=False) # تكلفة النقرة بالعملات (إلزامي)
    category = db.Column(db.String(80), nullable=True, index=True) # الفئة (اختياري)
    subcategory = db.Column(db.String(80), nullable=True) # الفئة الفرعية (اختياري)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow) # تاريخ الإنشاء
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow) # تاريخ التحديث
    is_active = db.Column(db.Boolean, nullable=False, default=True) # هل الإعلان نشط؟
    # --- START: إضافة حقل الموافقة ---
    is_approved = db.Column(db.Boolean, nullable=False, default=False, index=True) # هل تمت الموافقة على الإعلان؟ (افتراضي لا) - تمت إضافة index
    # --- END: إضافة حقل الموافقة ---
    # images = db.Column(db.Text, nullable=True) # حقل للصور إذا أردت إضافتها لاحقًا (مثل _save_entity)

    # --- START: إضافة دوال للاهتمامات ---
    def set_interests(self, interests_list):
        """تحويل قائمة الاهتمامات إلى نص JSON لتخزينها."""
        if interests_list and isinstance(interests_list, list):
             # التأكد من أن كل عنصر في القائمة هو نص
            if all(isinstance(item, str) for item in interests_list):
                self.interests = json.dumps(interests_list)
            else:
                app.logger.warning(f"Ad {self.id}: Interests list contains non-string elements. Setting interests to null.")
                self.interests = None
        else:
            self.interests = None # أو json.dumps([])

    def get_interests(self):
        """استرجاع قائمة الاهتمامات من نص JSON."""
        if self.interests:
            try:
                return json.loads(self.interests)
            except json.JSONDecodeError:
                app.logger.error(f"Ad {self.id}: Failed to decode interests JSON: {self.interests}")
                return [] # إرجاع قائمة فارغة في حالة الخطأ
        return []
    # --- END: إضافة دوال للاهتمامات ---

    def to_dict(self):
        """إرجاع بيانات الإعلان كقاموس."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "title": self.title,
            "description": self.description,
            "link": self.link,
            # --- START: تعديل لاستخدام الدالة ---
            "interests": self.get_interests(), # استرجاع القائمة الفعلية
            # --- END: تعديل لاستخدام الدالة ---
            "number_of_clicks": self.number_of_clicks,
            "coin_per_click": self.coin_per_click,
            "category": self.category,
            "subcategory": self.subcategory,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "is_active": self.is_active,
            # --- START: إضافة حقل الموافقة إلى القاموس ---
            "is_approved": self.is_approved,
            # --- END: إضافة حقل الموافقة إلى القاموس ---
            # "images": json.loads(self.images) if self.images else [] # إذا أضفت الصور
        }

    def __repr__(self):
        """تمثيل نصي للإعلان."""
        return f'<Advertisement {self.id} - {self.title}>'

# --- تهيئة قاعدة البيانات (إنشاء الجداول إذا لم تكن موجودة) ---
# هذا الكود يتم تشغيله مرة واحدة عند بدء تشغيل التطبيق (استيراد الوحدة)
# نستخدم app.app_context() لضمان توفر سياق التطبيق لـ SQLAlchemy
try:
    with app.app_context():
        print(f"Initializing database tables at: {db_path}...")
        db.create_all() # يقوم بإنشاء الجداول المعرفة أعلاه إذا لم تكن موجودة
        print("Database tables checked/created successfully.")
except Exception as e:
    # من المهم تسجيل هذا الخطأ لأنه قد يمنع التطبيق من العمل بشكل صحيح
    print(f"FATAL ERROR during initial db.create_all(): {e}")
    # يمكنك اختيار الخروج هنا لمنع بدء تشغيل التطبيق مع قاعدة بيانات غير مهيأة
    sys.exit(f"Database initialization failed: {e}")


# --- دوال مساعدة وامتدادات مسموحة ---
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ... (بقية الدوال المساعدة: _handle_image_upload, _save_entity) ...
# هذه الدوال غير مستخدمة حاليًا في الكود المنقح ولكنها قد تكون مفيدة لاحقًا
def _handle_image_upload():
    uploaded_filenames = []
    if 'images' in request.files:
        image_files = request.files.getlist('images')
        for file in image_files:
            if file and file.filename != '' and allowed_file(file.filename):
                original_filename = secure_filename(file.filename)
                unique_suffix = str(uuid.uuid4().hex)[:8]
                filename = f"{unique_suffix}_{original_filename}"
                save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                try: file.save(save_path); uploaded_filenames.append(filename)
                except Exception as e:
                    app.logger.error(f"Err saving {filename}: {e}")
                    # محاولة حذف الملفات التي تم رفعها بالفعل في حالة حدوث خطأ
                    for fname in uploaded_filenames:
                        try: os.remove(os.path.join(app.config['UPLOAD_FOLDER'], fname))
                        except OSError: pass # تجاهل الخطأ إذا لم يتم العثور على الملف
                    # لا ترجع خطأ 500 هنا مباشرة، فقط أرجع قائمة فارغة أو مؤشر خطأ
                    # سنعتمد على معالجة الأخطاء في _save_entity
                    return None # أو أثر استثناء مخصص
            elif file and file.filename != '': app.logger.warning(f"Skip disallowed: {file.filename}")
    return uploaded_filenames

def _save_entity(entity, uploaded_filenames):
    # تحقق مما إذا كان _handle_image_upload قد أرجع None (مؤشر خطأ)
    if uploaded_filenames is None:
         return jsonify({"error": "Error processing uploaded images"}), 500
    try:
        # تعيين الصور فقط إذا كانت هناك ملفات مرفوعة
        if uploaded_filenames:
            entity.images = json.dumps(uploaded_filenames)
        else:
             # تأكد من أن الحقل فارغ إذا لم يتم رفع صور أو إذا كانت كلها غير مسموحة
             entity.images = None

        db.session.add(entity)
        db.session.commit()
        entity_type = entity.__class__.__name__.lower().replace("advertisement", "")
        if not entity_type or entity_type == "advertisement": entity_type = "advertisement" # التعامل مع الحالة الأساسية
        entity_dict = entity.to_dict() # احصل على القاموس بعد الـ commit (للحصول على الـ ID)
        # --- تعديل الرسالة لتعكس حالة الموافقة الأولية ---
        # return jsonify({"message": f"{entity_type.replace('_',' ').capitalize()} submitted for approval!", "advertisement": entity_dict}), 201
        return jsonify({"message": f"{entity_type.replace('_',' ').capitalize()} created successfully!", "advertisement": entity_dict}), 201

    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Err creating {entity.__class__.__name__} (User: {getattr(entity, 'user_id', 'N/A')}): {e}", exc_info=True) # إضافة تفاصيل الخطأ
        # حذف الملفات المرفوعة في حالة فشل قاعدة البيانات
        if uploaded_filenames:
            for filename in uploaded_filenames:
                try:
                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    if os.path.exists(filepath):
                         os.remove(filepath)
                         app.logger.info(f"Cleaned up image {filename} after DB error.")
                except OSError:
                    app.logger.error(f"Could not remove {filename} after db error.")
        return jsonify({"error": f"Internal server error creating {entity_type}"}), 500


@app.route('/register', methods=['POST'])
def register():
    """نقطة نهاية لإنشاء مستخدم جديد."""
    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400 # Bad Request

    data = request.get_json()
    name = data.get('name')
    email = data.get('email')
    password = data.get('password')
    phone_number = data.get('phone_number')
    # --- START: إضافة استخراج الاهتمامات ---
    interests_list = data.get('interests') # اختياري
    # --- END: إضافة استخراج الاهتمامات ---


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

    # --- START: التحقق من نوع الاهتمامات ---
    if interests_list is not None and not isinstance(interests_list, list):
        return jsonify({"error": "Field 'interests' must be a list of strings"}), 400
    if interests_list and not all(isinstance(item, str) for item in interests_list):
         return jsonify({"error": "All items in 'interests' list must be strings"}), 400
    # --- END: التحقق من نوع الاهتمامات ---

    # إنشاء مستخدم جديد
    new_user = User(name=name, email=email, phone_number=phone_number)
    new_user.set_password(password) # تعيين كلمة المرور المشفرة
    # --- START: تعيين الاهتمامات للمستخدم الجديد ---
    new_user.set_interests(interests_list) # تعيين الاهتمامات باستخدام الدالة المساعدة
    # --- END: تعيين الاهتمامات للمستخدم الجديد ---

    try:
        db.session.add(new_user)
        db.session.commit()
        # إرجاع بيانات المستخدم الجديد (باستثناء كلمة المرور)
        return jsonify({
            "message": "User registered successfully!",
            "user": new_user.to_dict() # سيحتوي الآن على الاهتمامات
        }), 201 # Created
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Registration Error: {e}", exc_info=True) # إضافة تفاصيل الخطأ
        return jsonify({"error": "Internal Server Error during registration"}), 500 # Internal Server Error


@app.route('/login', methods=['POST'])
def login():
    """نقطة نهاية لتسجيل دخول المستخدم."""
    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400

    data = request.get_json()
    email = data.get('email')
    password = data.get('password')

    # التحقق من وجود الحقول المطلوبة
    if not email or not password:
        return jsonify({"error": "Missing email or password"}), 400

    # البحث عن المستخدم بواسطة البريد الإلكتروني
    user = User.query.filter_by(email=email).first()

    # التحقق من وجود المستخدم وصحة كلمة المرور
    if user is None or not user.check_password(password):
        # رسالة خطأ عامة لأسباب أمنية
        return jsonify({"error": "Invalid email or password"}), 401 # Unauthorized

    # تسجيل الدخول ناجح، إرجاع بيانات المستخدم
    return jsonify({
        "message": "Login successful!",
        "user": user.to_dict() # سيحتوي الآن على الاهتمامات
    }), 200 # OK

# --- START: نقطة نهاية لجلب بيانات المستخدم بالـ ID ---
@app.route('/users/<int:user_id>', methods=['GET'])
def get_user_by_id(user_id):
    """نقطة نهاية لجلب بيانات مستخدم معين بواسطة ID."""
    user = User.query.get(user_id) # استخدام .get() للبحث بالـ Primary Key

    if user is None:
        return jsonify({"error": f"User with ID {user_id} not found"}), 404 # Not Found

    return jsonify(user.to_dict()), 200 # OK
# --- END: نقطة نهاية لجلب بيانات المستخدم بالـ ID ---

# --- START: نقطة نهاية لتحديث اهتمامات المستخدم ---
@app.route('/users/<int:user_id>/interests', methods=['PUT'])
def update_user_interests(user_id):
    """نقطة نهاية لتحديث قائمة اهتمامات المستخدم."""
    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400

    user = User.query.get(user_id)
    if user is None:
        return jsonify({"error": f"User with ID {user_id} not found"}), 404

    data = request.get_json()
    interests_list = data.get('interests')

    # التحقق من أن الاهتمامات مرسلة وهي قائمة
    if interests_list is None:
        return jsonify({"error": "Missing 'interests' field in request body"}), 400
    if not isinstance(interests_list, list):
        return jsonify({"error": "Field 'interests' must be a list of strings"}), 400
    if not all(isinstance(item, str) for item in interests_list):
        return jsonify({"error": "All items in 'interests' list must be strings"}), 400

    try:
        user.set_interests(interests_list) # استخدام الدالة المساعدة للتحديث
        db.session.commit()
        return jsonify({
            "message": f"User {user_id} interests updated successfully",
            "user": user.to_dict()
        }), 200 # OK
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error updating interests for user {user_id}: {e}", exc_info=True)
        return jsonify({"error": "Internal Server Error updating interests"}), 500
# --- END: نقطة نهاية لتحديث اهتمامات المستخدم ---


@app.route('/add_advertisement', methods=['POST'])
def add_advertisement():
    """نقطة نهاية لإنشاء إعلان جديد (سيحتاج لموافقة)."""
    # ملاحظة: يجب استخدام المصادقة لتحديد user_id بشكل آمن
    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400

    data = request.get_json()

    # --- استخراج البيانات ---
    user_id = data.get('user_id') # هام: يجب التحقق من أن هذا المستخدم موجود وله الصلاحية
    title = data.get('title')
    link = data.get('link')
    coin_per_click = data.get('coin_per_click')
    description = data.get('description') # اختياري
    interests_list = data.get('interests') # اختياري (يجب أن تكون قائمة)
    category = data.get('category') # اختياري
    subcategory = data.get('subcategory') # اختياري

    # --- التحقق من الحقول الإلزامية ---
    missing_fields = []
    if user_id is None: missing_fields.append('user_id')
    if not title: missing_fields.append('title')
    if not link: missing_fields.append('link')
    if coin_per_click is None: missing_fields.append('coin_per_click')
    if missing_fields:
        return jsonify({"error": f"Missing required fields: {', '.join(missing_fields)}"}), 400

    # --- التحقق من صحة البيانات ---
    # 1. التحقق من وجود المستخدم (مهم!)
    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": f"User with ID {user_id} not found"}), 404 # Not Found

    # 2. التحقق من نوع الاهتمامات (إذا تم توفيرها)
    if interests_list is not None and not isinstance(interests_list, list):
        return jsonify({"error": "Field 'interests' must be a list of strings"}), 400
    if interests_list and not all(isinstance(item, str) for item in interests_list):
         return jsonify({"error": "All items in 'interests' list must be strings"}), 400

    # 3. التحقق من نوع coin_per_click
    if not isinstance(coin_per_click, int) or coin_per_click < 0:
         return jsonify({"error": "Field 'coin_per_click' must be a non-negative integer"}), 400

    # --- إنشاء وحفظ الإعلان ---
    new_ad = Advertisement(
        user_id=user_id,
        title=title,
        description=description,
        link=link,
        coin_per_click=coin_per_click,
        category=category,
        subcategory=subcategory
        # is_approved سيكون False افتراضيًا
        # is_active سيكون True افتراضيًا
    )
    # تعيين الاهتمامات باستخدام الدالة المساعدة
    new_ad.set_interests(interests_list)

    try:
        db.session.add(new_ad)
        db.session.commit()
        # إرجاع بيانات الإعلان الجديد (بما في ذلك is_approved=False)
        return jsonify({
            "message": "Advertisement created successfully and submitted for approval!",
            "advertisement": new_ad.to_dict()
        }), 201 # Created
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error creating advertisement for user {user_id}: {e}", exc_info=True)
        return jsonify({"error": "Internal Server Error creating advertisement"}), 500

# --- START: نقطة نهاية للموافقة على إعلان (للأدمن) ---
# ملاحظة هامة: هذه النقطة يجب أن تكون محمية! يجب التأكد أن المستخدم الذي يستدعيها هو أدمن.
# طرق الحماية الشائعة تتضمن: التحقق من توكن خاص بالأدمن، التحقق من دور المستخدم، إلخ.
@app.route('/admin/advertisements/<int:ad_id>/approve', methods=['PUT'])
def approve_advertisement(ad_id):
    """نقطة نهاية للموافقة على إعلان معين (تغيير is_approved إلى True)."""
    advertisement = Advertisement.query.get(ad_id)

    if advertisement is None:
        return jsonify({"error": f"Advertisement with ID {ad_id} not found"}), 404

    if advertisement.is_approved:
        return jsonify({
            "message": f"Advertisement {ad_id} is already approved.",
            "advertisement": advertisement.to_dict()
        }), 200 # OK (أو 304 Not Modified إذا أردت)

    try:
        advertisement.is_approved = True
        advertisement.updated_at = datetime.utcnow() # تحديث وقت التعديل
        db.session.commit()
        return jsonify({
            "message": f"Advertisement {ad_id} approved successfully.",
            "advertisement": advertisement.to_dict()
        }), 200 # OK
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error approving advertisement {ad_id}: {e}", exc_info=True)
        return jsonify({"error": "Internal Server Error approving advertisement"}), 500
# --- END: نقطة نهاية للموافقة على إعلان ---

# --- START: نقطة نهاية لجلب جميع الإعلانات (بما في ذلك غير الموافق عليها) ---
@app.route('/advertisements', methods=['GET'])
def get_all_advertisements():
    """نقطة نهاية لجلب جميع الإعلانات (مناسب للأدمن)."""
    # يمكن إضافة pagination هنا في تطبيق حقيقي للتعامل مع عدد كبير من الإعلانات
    # page = request.args.get('page', 1, type=int)
    # per_page = request.args.get('per_page', 10, type=int)
    # ads = Advertisement.query.paginate(page=page, per_page=per_page, error_out=False)
    # results = [ad.to_dict() for ad in ads.items]
    # return jsonify({
    #     "advertisements": results,
    #     "total": ads.total,
    #     "pages": ads.pages,
    #     "current_page": page
    # })

    all_ads = Advertisement.query.order_by(Advertisement.created_at.desc()).all()
    results = [ad.to_dict() for ad in all_ads]
    return jsonify(results), 200
# --- END: نقطة نهاية لجلب جميع الإعلانات ---

# --- START: نقطة نهاية لجلب الإعلانات الموافق عليها فقط ---
@app.route('/advertisements/approved', methods=['GET'])
def get_approved_advertisements():
    """نقطة نهاية لجلب الإعلانات التي تمت الموافقة عليها فقط."""
    # يمكن إضافة pagination هنا أيضًا
    approved_ads = Advertisement.query.filter_by(is_approved=True, is_active=True)\
                                      .order_by(Advertisement.created_at.desc()).all()
                                      # أضفنا is_active=True هنا، قد ترغب بعرض الموافق عليها حتى لو غير نشطة للأدمن
                                      # لكن للمستخدمين العاديين، عادة ما تعرض الموافق عليها والنشطة فقط.
    results = [ad.to_dict() for ad in approved_ads]
    return jsonify(results), 200
# --- END: نقطة نهاية لجلب الإعلانات الموافق عليها فقط ---


# --- التشغيل المحلي (للاختبار فقط) ---
if __name__ == '__main__':
    # لا حاجة لـ db.create_all() هنا، فقد تم تشغيله أعلاه
    print("Starting Flask development server (for local testing)...")
    # استخدم debug=True فقط أثناء التطوير المحلي، وليس في الإنتاج
    # استخدم المنفذ 5000 أو أي منفذ آخر مناسب للاختبار المحلي
    # تغيير host='0.0.0.0' لجعله متاحًا على الشبكة المحلية (إذا لزم الأمر)
    app.run(debug=True, host='0.0.0.0', port=5000)

# --- END OF MODIFIED FILE app.py ---
