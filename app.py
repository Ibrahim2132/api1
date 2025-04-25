# --- START OF FILE app.py ---
import os
import json
import uuid
import sys # استيراد sys للخروج عند الخطأ إذا لزم الأمر
from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

# --- تحديد المسارات ---

persistent_data_dir = '/tmp'
db_path = os.path.join(persistent_data_dir, 'database.db')
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

# --- تعريف موديلات قاعدة البيانات وجداول الربط ---

# جدول لربط المستخدمين بالإعلانات العامة المفضلة
user_favorite_advertisement = db.Table('user_favorite_advertisement',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('advertisement_id', db.Integer, db.ForeignKey('advertisement.id'), primary_key=True)
)
# جدول لربط المستخدمين بإعلانات السيارات المفضلة
user_favorite_car = db.Table('user_favorite_car',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('car_advertisement_id', db.Integer, db.ForeignKey('car_advertisement.id'), primary_key=True)
)
# جدول لربط المستخدمين بإعلانات العقارات المفضلة
user_favorite_real_estate = db.Table('user_favorite_real_estate',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('real_estate_advertisement_id', db.Integer, db.ForeignKey('real_estate_advertisement.id'), primary_key=True)
)

# --- تعريف موديل المستخدم (User Model) ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    phone_number = db.Column(db.String(20), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    advertisements = db.relationship('Advertisement', backref='author', lazy='dynamic')
    car_advertisements = db.relationship('CarAdvertisement', backref='author', lazy='dynamic')
    real_estate_advertisements = db.relationship('RealEstateAdvertisement', backref='author', lazy='dynamic')
    favorite_ads = db.relationship('Advertisement', secondary=user_favorite_advertisement, lazy='dynamic', back_populates='favorited_by_users')
    favorite_car_ads = db.relationship('CarAdvertisement', secondary=user_favorite_car, lazy='dynamic', back_populates='favorited_by_users')
    favorite_real_estate_ads = db.relationship('RealEstateAdvertisement', secondary=user_favorite_real_estate, lazy='dynamic', back_populates='favorited_by_users')
    def set_password(self, password): self.password_hash = generate_password_hash(password)
    def check_password(self, password): return check_password_hash(self.password_hash, password)
    def to_dict(self): return {"id": self.id, "name": self.name, "phone_number": self.phone_number}
    def __repr__(self): return f'<User {self.name} - {self.phone_number}>'

# --- تعريف موديل المستخدم (User Model) ---
class User1(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True) # البريد الإلكتروني فريد ومطلوب
    phone_number = db.Column(db.String(20), nullable=False) # رقم الهاتف مطلوب
    password_hash = db.Column(db.String(128), nullable=False) # تخزين هاش كلمة المرور

    def set_password(self, password):
        """إنشاء هاش لكلمة المرور."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """التحقق من تطابق كلمة المرور المدخلة مع الهاش المخزن."""
        return check_password_hash(self.password_hash, password)

    def to_dict(self):
        """إرجاع بيانات المستخدم كقاموس (بدون كلمة المرور)."""
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "phone_number": self.phone_number
        }

    def __repr__(self):
        """تمثيل نصي للمستخدم (مفيد للتصحيح)."""
        return f'<User {self.name} - {self.email}>'

# --- تعريف موديل الإعلان العام (Advertisement Model) ---
class Advertisement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(100), nullable=False); type = db.Column(db.String(100), nullable=False)
    city = db.Column(db.String(100), nullable=False); subcity = db.Column(db.String(100), nullable=True)
    title = db.Column(db.String(200), nullable=False); description = db.Column(db.Text, nullable=False)
    phone_number = db.Column(db.String(20), nullable=False); price = db.Column(db.Float, nullable=False)
    images = db.Column(db.Text, nullable=True); user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    is_approved = db.Column(db.Boolean, default=False, nullable=False, index=True)
    favorited_by_users = db.relationship('User', secondary=user_favorite_advertisement, lazy='dynamic', back_populates='favorite_ads')
    def to_dict(self):
        image_list = json.loads(self.images) if self.images else []
        return {"id": self.id, "category": self.category, "type": self.type, "city": self.city, "subcity": self.subcity, "title": self.title, "description": self.description, "phone_number": self.phone_number, "price": self.price, "images": image_list, "user_id": self.user_id, "is_approved": self.is_approved}
    def __repr__(self): return f'<Advertisement {self.id} - {self.title} (Approved: {self.is_approved})>'

# --- تعريف موديل إعلان السيارة (CarAdvertisement Model) ---
class CarAdvertisement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    city = db.Column(db.String(100), nullable=False); subcity = db.Column(db.String(100), nullable=True)
    title = db.Column(db.String(200), nullable=False); description = db.Column(db.Text, nullable=False)
    phone_number = db.Column(db.String(20), nullable=False); price = db.Column(db.Float, nullable=False)
    images = db.Column(db.Text, nullable=True); user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    state = db.Column(db.String(50), nullable=False); car_category = db.Column(db.String(100), nullable=False)
    car_subcategory = db.Column(db.String(100), nullable=False); modelyear = db.Column(db.Integer, nullable=False)
    kilometer = db.Column(db.Integer, nullable=False); is_approved = db.Column(db.Boolean, default=False, nullable=False, index=True)
    favorited_by_users = db.relationship('User', secondary=user_favorite_car, lazy='dynamic', back_populates='favorite_car_ads')
    def to_dict(self):
        image_list = json.loads(self.images) if self.images else []
        return {"id": self.id, "city": self.city, "subcity": self.subcity, "title": self.title, "description": self.description, "phone_number": self.phone_number, "price": self.price, "images": image_list, "user_id": self.user_id, "state": self.state, "car_category": self.car_category, "car_subcategory": self.car_subcategory, "modelyear": self.modelyear, "kilometer": self.kilometer, "is_approved": self.is_approved}
    def __repr__(self): return f'<CarAdvertisement {self.id} - {self.title} (Approved: {self.is_approved})>'

# --- تعريف موديل إعلان العقار (RealEstateAdvertisement Model) ---
class RealEstateAdvertisement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    city = db.Column(db.String(100), nullable=False); subcity = db.Column(db.String(100), nullable=True)
    title = db.Column(db.String(200), nullable=False); description = db.Column(db.Text, nullable=False)
    phone_number = db.Column(db.String(20), nullable=False); price = db.Column(db.Float, nullable=False)
    images = db.Column(db.Text, nullable=True); user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    type = db.Column(db.String(100), nullable=False); distance = db.Column(db.Float, nullable=True)
    num_bed = db.Column(db.Integer, nullable=False); num_bath = db.Column(db.Integer, nullable=False)
    is_approved = db.Column(db.Boolean, default=False, nullable=False, index=True)
    favorited_by_users = db.relationship('User', secondary=user_favorite_real_estate, lazy='dynamic', back_populates='favorite_real_estate_ads')
    def to_dict(self):
        image_list = json.loads(self.images) if self.images else []
        return {"id": self.id, "city": self.city, "subcity": self.subcity, "title": self.title, "description": self.description, "phone_number": self.phone_number, "price": self.price, "images": image_list, "user_id": self.user_id, "type": self.type, "distance": self.distance, "num_bed": self.num_bed, "num_bath": self.num_bath, "is_approved": self.is_approved}
    def __repr__(self): return f'<RealEstateAdvertisement {self.id} - {self.title} (Approved: {self.is_approved})>'


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
        return jsonify({"message": f"{entity_type.replace('_',' ').capitalize()} submitted for approval!", "advertisement": entity_dict}), 201
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


# --- نقاط النهاية للمستخدمين (Register, Login, Get Profile) ---
@app.route('/register', methods=['POST'])
def register():
    if not request.is_json: return jsonify({"error": "Missing JSON in request"}), 400
    data = request.get_json()
    name = data.get('name')
    password = data.get('password')
    phone_number = data.get('phone_number')

    if not name or not password or not phone_number:
        return jsonify({"error": "Missing required fields (name, password, phone_number)"}), 400

    # التحقق يتم الآن بأمان لأن الجداول مضمونة الوجود (نظريًا)
    if User.query.filter_by(phone_number=phone_number).first():
        return jsonify({"error": "Phone number already registered"}), 409

    new_user = User(name=name, phone_number=phone_number)
    new_user.set_password(password)
    try:
        db.session.add(new_user)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Registration Error for phone {phone_number}: {e}", exc_info=True)
        return jsonify({"error": "Internal Server Error during registration"}), 500 # رسالة عامة للمستخدم

    return jsonify({"message": "User registered successfully!", "user": new_user.to_dict()}), 201

# ... (بقية نقاط النهاية: login, get_user_profile, add_advertisement, add_car, add_re, get_all, admin, favorites) ...
# (الكود الخاص بنقاط النهاية الأخرى يبقى كما هو)
@app.route('/login', methods=['POST'])
def login(): # ... (الكود كما هو)
    if not request.is_json: return jsonify({"error": "Missing JSON in request"}), 400
    data = request.get_json(); phone_number, password = data.get('phone_number'), data.get('password')
    if not phone_number or not password: return jsonify({"error": "Missing phone_number or password"}), 400
    user = User.query.filter_by(phone_number=phone_number).first()
    if user is None or not user.check_password(password): return jsonify({"error": "Invalid credentials"}), 401
    return jsonify({"message": "Login successful!", "user": user.to_dict()}), 200

@app.route('/user/<int:user_id>', methods=['GET'])
def get_user_profile(user_id): # ... (الكود كما هو)
    user = User.query.get_or_404(user_id)
    return jsonify({"user": user.to_dict()}), 200

# --- نقاط النهاية لإضافة الإعلانات (POST) ---
@app.route('/advertisements', methods=['POST'])
def add_advertisement():
    required=['user_id', 'category', 'type', 'city', 'title', 'description', 'phone_number', 'price']
    form=request.form; missing=[f for f in required if f not in form];
    if missing: return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400
    uid=form.get('user_id'); user=User.query.get(uid);
    if user is None: return jsonify({"error": f"User with id {uid} not found"}), 404
    try: price=float(form.get('price'))
    except ValueError: return jsonify({"error": "Invalid price format"}), 400

    uploads=_handle_image_upload();
    if uploads is None: # تحقق من الخطأ أثناء الرفع
         return jsonify({"error": "Failed to process or save uploaded images."}), 500

    new_ad = Advertisement(user_id=uid, category=form.get('category'), type=form.get('type'), city=form.get('city'), subcity=form.get('subcity'), title=form.get('title'), description=form.get('description'), phone_number=form.get('phone_number'), price=price) # لا نضع الصور هنا بعد
    return _save_entity(new_ad, uploads) # _save_entity سيهتم بالصور وقاعدة البيانات

@app.route('/car_advertisements', methods=['POST'])
def add_car_advertisement():
    required=['user_id','city','title','description','phone_number','price','state','car_category','car_subcategory','modelyear','kilometer']
    form=request.form; missing=[f for f in required if f not in form];
    if missing: return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400
    uid=form.get('user_id'); user=User.query.get(uid);
    if user is None: return jsonify({"error": f"User with id {uid} not found"}), 404
    try: price=float(form.get('price'))
    except ValueError: return jsonify({"error": "Invalid price format"}), 400
    try: modelyear=int(form.get('modelyear'))
    except ValueError: return jsonify({"error": "Invalid modelyear format"}), 400
    try: km=int(form.get('kilometer'))
    except ValueError: return jsonify({"error": "Invalid kilometer format"}), 400

    uploads=_handle_image_upload();
    if uploads is None: return jsonify({"error": "Failed to process or save uploaded images."}), 500

    new_car=CarAdvertisement(user_id=uid,city=form.get('city'),subcity=form.get('subcity'),title=form.get('title'),description=form.get('description'),phone_number=form.get('phone_number'),price=price,state=form.get('state'),car_category=form.get('car_category'),car_subcategory=form.get('car_subcategory'),modelyear=modelyear,kilometer=km)
    return _save_entity(new_car, uploads)

@app.route('/real_estate_advertisements', methods=['POST'])
def add_real_estate_advertisement():
    required=['user_id','city','title','description','phone_number','price','type','num_bed','num_bath']
    form=request.form; missing=[f for f in required if f not in form];
    if missing: return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400
    uid=form.get('user_id'); user=User.query.get(uid);
    if user is None: return jsonify({"error": f"User with id {uid} not found"}), 404
    try: price=float(form.get('price'))
    except ValueError: return jsonify({"error": "Invalid price format"}), 400
    try: beds=int(form.get('num_bed'))
    except ValueError: return jsonify({"error": "Invalid num_bed format"}), 400
    try: baths=int(form.get('num_bath'))
    except ValueError: return jsonify({"error": "Invalid num_bath format"}), 400
    dist=None; dist_str=form.get('distance')
    if dist_str:
        try: dist=float(dist_str)
        except ValueError: return jsonify({"error": "Invalid distance format"}), 400

    uploads=_handle_image_upload();
    if uploads is None: return jsonify({"error": "Failed to process or save uploaded images."}), 500

    new_re=RealEstateAdvertisement(user_id=uid,city=form.get('city'),subcity=form.get('subcity'),title=form.get('title'),description=form.get('description'),phone_number=form.get('phone_number'),price=price,type=form.get('type'),distance=dist,num_bed=beds,num_bath=baths)
    return _save_entity(new_re, uploads)

# === نقاط النهاية لجلب الإعلانات للمستخدم (فقط الموافق عليها) ===
@app.route('/advertisements/all', methods=['GET'])
def get_all_advertisements():
    try: ads = Advertisement.query.filter_by(is_approved=True).all(); result = [ad.to_dict() for ad in ads]
    except Exception as e: app.logger.error(f"Err fetch approved ads: {e}"); return jsonify({"error":"Internal Server Error"}),500
    return jsonify(result), 200
@app.route('/car_advertisements/all', methods=['GET'])
def get_all_car_advertisements():
    try: ads = CarAdvertisement.query.filter_by(is_approved=True).all(); result = [ad.to_dict() for ad in ads]
    except Exception as e: app.logger.error(f"Err fetch approved car ads: {e}"); return jsonify({"error":"Internal Server Error"}),500
    return jsonify(result), 200
@app.route('/real_estate_advertisements/all', methods=['GET'])
def get_all_real_estate_advertisements():
    try: ads = RealEstateAdvertisement.query.filter_by(is_approved=True).all(); result = [ad.to_dict() for ad in ads]
    except Exception as e: app.logger.error(f"Err fetch approved re ads: {e}"); return jsonify({"error":"Internal Server Error"}),500
    return jsonify(result), 200

# === نقاط نهاية جديدة خاصة بـ Admin ===
# !! تذكير: يجب إضافة آلية تحقق من صلاحيات المشرف هنا !!
@app.route('/admin/advertisements/pending', methods=['GET'])
def admin_get_pending_advertisements(): # Add admin auth check
    try: ads = Advertisement.query.filter_by(is_approved=False).all(); result = [ad.to_dict() for ad in ads]
    except Exception as e: app.logger.error(f"Err fetch pending ads: {e}"); return jsonify({"error":"Internal Server Error"}),500
    return jsonify(result), 200
@app.route('/admin/car_advertisements/pending', methods=['GET'])
def admin_get_pending_car_advertisements(): # Add admin auth check
    try: ads = CarAdvertisement.query.filter_by(is_approved=False).all(); result = [ad.to_dict() for ad in ads]
    except Exception as e: app.logger.error(f"Err fetch pending car ads: {e}"); return jsonify({"error":"Internal Server Error"}),500
    return jsonify(result), 200
@app.route('/admin/real_estate_advertisements/pending', methods=['GET'])
def admin_get_pending_real_estate_advertisements(): # Add admin auth check
    try: ads = RealEstateAdvertisement.query.filter_by(is_approved=False).all(); result = [ad.to_dict() for ad in ads]
    except Exception as e: app.logger.error(f"Err fetch pending re ads: {e}"); return jsonify({"error":"Internal Server Error"}),500
    return jsonify(result), 200
@app.route('/admin/advertisements/<int:ad_id>/approve', methods=['PUT'])
def admin_approve_advertisement(ad_id): # Add admin auth check
    ad = Advertisement.query.get_or_404(ad_id);
    if ad.is_approved: return jsonify({"message": "Advertisement already approved."}), 200
    ad.is_approved = True;
    try: db.session.commit(); return jsonify({"message": f"Advertisement {ad_id} approved.", "advertisement": ad.to_dict()}), 200
    except Exception as e: db.session.rollback(); app.logger.error(f"Err approve ad {ad_id}: {e}"); return jsonify({"error":"Internal Server Error"}),500
@app.route('/admin/car_advertisements/<int:ad_id>/approve', methods=['PUT'])
def admin_approve_car_advertisement(ad_id): # Add admin auth check
    ad = CarAdvertisement.query.get_or_404(ad_id);
    if ad.is_approved: return jsonify({"message": "Car advertisement already approved."}), 200
    ad.is_approved = True;
    try: db.session.commit(); return jsonify({"message": f"Car Ad {ad_id} approved.", "advertisement": ad.to_dict()}), 200
    except Exception as e: db.session.rollback(); app.logger.error(f"Err approve car ad {ad_id}: {e}"); return jsonify({"error":"Internal Server Error"}),500
@app.route('/admin/real_estate_advertisements/<int:ad_id>/approve', methods=['PUT'])
def admin_approve_real_estate_advertisement(ad_id): # Add admin auth check
    ad = RealEstateAdvertisement.query.get_or_404(ad_id);
    if ad.is_approved: return jsonify({"message": "Real estate advertisement already approved."}), 200
    ad.is_approved = True;
    try: db.session.commit(); return jsonify({"message": f"RE Ad {ad_id} approved.", "advertisement": ad.to_dict()}), 200
    except Exception as e: db.session.rollback(); app.logger.error(f"Err approve re ad {ad_id}: {e}"); return jsonify({"error":"Internal Server Error"}),500

# === نقاط نهاية جديدة خاصة بالمفضلة ===
# !! تذكير: يجب إضافة آلية تحقق من أن المستخدم هو صاحب الطلب !!
@app.route('/user/<int:user_id>/favorites/advertisements/<int:ad_id>', methods=['POST'])
def add_ad_to_favorites(user_id, ad_id):
    user = User.query.get_or_404(user_id)
    ad = Advertisement.query.get_or_404(ad_id)
    # Check authorization: Is the logged-in user the same as user_id? (Needs implementation)
    if ad in user.favorite_ads:
         return jsonify({"message": "Advertisement already in favorites."}), 200
    user.favorite_ads.append(ad)
    try: db.session.commit(); return jsonify({"message": "Advertisement added to favorites successfully."}), 201
    except Exception as e: db.session.rollback(); app.logger.error(f"Error adding ad {ad_id} to user {user_id} favorites: {e}"); return jsonify({"error": "Internal server error adding favorite"}), 500

@app.route('/user/<int:user_id>/favorites/cars/<int:ad_id>', methods=['POST'])
def add_car_ad_to_favorites(user_id, ad_id):
    user = User.query.get_or_404(user_id)
    ad = CarAdvertisement.query.get_or_404(ad_id)
    # Check authorization
    if ad in user.favorite_car_ads:
         return jsonify({"message": "Car advertisement already in favorites."}), 200
    user.favorite_car_ads.append(ad)
    try: db.session.commit(); return jsonify({"message": "Car advertisement added to favorites successfully."}), 201
    except Exception as e: db.session.rollback(); app.logger.error(f"Error adding car ad {ad_id} to user {user_id} fav: {e}"); return jsonify({"error": "Internal server error adding favorite"}), 500

@app.route('/user/<int:user_id>/favorites/real_estate/<int:ad_id>', methods=['POST'])
def add_real_estate_ad_to_favorites(user_id, ad_id):
    user = User.query.get_or_404(user_id)
    ad = RealEstateAdvertisement.query.get_or_404(ad_id)
    # Check authorization
    if ad in user.favorite_real_estate_ads:
         return jsonify({"message": "Real estate advertisement already in favorites."}), 200
    user.favorite_real_estate_ads.append(ad)
    try: db.session.commit(); return jsonify({"message": "Real estate advertisement added to favorites successfully."}), 201
    except Exception as e: db.session.rollback(); app.logger.error(f"Error adding re ad {ad_id} to user {user_id} fav: {e}"); return jsonify({"error": "Internal server error adding favorite"}), 500

@app.route('/user/<int:user_id>/favorites/advertisements/<int:ad_id>', methods=['DELETE'])
def remove_ad_from_favorites(user_id, ad_id):
    user = User.query.get_or_404(user_id)
    ad = Advertisement.query.get_or_404(ad_id)
    # Check authorization
    if ad not in user.favorite_ads:
         return jsonify({"error": "Advertisement not found in favorites."}), 404
    user.favorite_ads.remove(ad)
    try: db.session.commit(); return '', 204
    except Exception as e: db.session.rollback(); app.logger.error(f"Error removing ad {ad_id} from user {user_id} favorites: {e}"); return jsonify({"error": "Internal server error removing favorite"}), 500

@app.route('/user/<int:user_id>/favorites/cars/<int:ad_id>', methods=['DELETE'])
def remove_car_ad_from_favorites(user_id, ad_id):
    user = User.query.get_or_404(user_id)
    ad = CarAdvertisement.query.get_or_404(ad_id)
    # Check authorization
    if ad not in user.favorite_car_ads:
         return jsonify({"error": "Car advertisement not found in favorites."}), 404
    user.favorite_car_ads.remove(ad)
    try: db.session.commit(); return '', 204
    except Exception as e: db.session.rollback(); app.logger.error(f"Error removing car ad {ad_id} from user {user_id} fav: {e}"); return jsonify({"error": "Internal server error removing favorite"}), 500

@app.route('/user/<int:user_id>/favorites/real_estate/<int:ad_id>', methods=['DELETE'])
def remove_real_estate_ad_from_favorites(user_id, ad_id):
    user = User.query.get_or_404(user_id)
    ad = RealEstateAdvertisement.query.get_or_404(ad_id)
    # Check authorization
    if ad not in user.favorite_real_estate_ads:
         return jsonify({"error": "Real estate advertisement not found in favorites."}), 404
    user.favorite_real_estate_ads.remove(ad)
    try: db.session.commit(); return '', 204
    except Exception as e: db.session.rollback(); app.logger.error(f"Error removing re ad {ad_id} from user {user_id} fav: {e}"); return jsonify({"error": "Internal server error removing favorite"}), 500

@app.route('/user/<int:user_id>/favorites', methods=['GET'])
def get_user_favorites(user_id):
    user = User.query.get_or_404(user_id)
    # Check authorization
    try:
        fav_ads = [ad.to_dict() for ad in user.favorite_ads.filter(Advertisement.is_approved==True).all()]
        fav_car_ads = [ad.to_dict() for ad in user.favorite_car_ads.filter(CarAdvertisement.is_approved==True).all()]
        fav_re_ads = [ad.to_dict() for ad in user.favorite_real_estate_ads.filter(RealEstateAdvertisement.is_approved==True).all()]
        all_favorites = { "advertisements": fav_ads, "car_advertisements": fav_car_ads, "real_estate_advertisements": fav_re_ads }
        return jsonify(all_favorites), 200
    except Exception as e: app.logger.error(f"Error fetching favorites for user {user_id}: {e}"); return jsonify({"error": "Internal server error fetching favorites"}), 500


@app.route('/register1', methods=['POST'])
def register1():
    """نقطة نهاية لإنشاء مستخدم جديد."""
    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400 # Bad Request

    data = request.get_json()
    name = data.get('name')
    email = data.get('email')
    password = data.get('password')
    phone_number = data.get('phone_number')

    # التحقق من وجود جميع الحقول المطلوبة
    missing_fields = []
    if not name: missing_fields.append('name')
    if not email: missing_fields.append('email')
    if not password: missing_fields.append('password')
    if not phone_number: missing_fields.append('phone_number')
    if missing_fields:
        return jsonify({"error": f"Missing required fields: {', '.join(missing_fields)}"}), 400

    # التحقق من أن البريد الإلكتروني غير مسجل مسبقًا
    if User1.query.filter_by(email=email).first():
        return jsonify({"error": "Email address already registered"}), 409 # Conflict

    # إنشاء مستخدم جديد
    new_user = User1(name=name, email=email, phone_number=phone_number)
    new_user.set_password(password) # تعيين كلمة المرور المشفرة

    try:
        db.session.add(new_user)
        db.session.commit()
        # إرجاع بيانات المستخدم الجديد (باستثناء كلمة المرور)
        return jsonify({
            "message": "User registered successfully!",
            "user": new_user.to_dict()
        }), 201 # Created
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Registration Error: {e}")
        return jsonify({"error": "Internal Server Error during registration"}), 500 # Internal Server Error


@app.route('/login1', methods=['POST'])
def login1():
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
    user = User1.query.filter_by(email=email).first()

    # التحقق من وجود المستخدم وصحة كلمة المرور
    if user is None or not user.check_password(password):
        # رسالة خطأ عامة لأسباب أمنية
        return jsonify({"error": "Invalid email or password"}), 401 # Unauthorized

    # تسجيل الدخول ناجح، إرجاع بيانات المستخدم
    return jsonify({
        "message": "Login successful!",
        "user": user.to_dict()
    }), 200 # OK

# --- التشغيل المحلي (للاختبار فقط) ---
if __name__ == '__main__':
    # لا حاجة لـ db.create_all() هنا، فقد تم تشغيله أعلاه
    print("Starting Flask development server (for local testing)...")
    # استخدم debug=True فقط أثناء التطوير المحلي، وليس في الإنتاج
    # استخدم المنفذ 5000 أو أي منفذ آخر مناسب للاختبار المحلي
    app.run(debug=True, host='0.0.0.0', port=5000)

# --- END OF FILE app.py ---
