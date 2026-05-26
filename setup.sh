#!/bin/bash
# ─────────────────────────────────────────
#  StudyNest Setup Script
#  Run once: bash setup.sh
# ─────────────────────────────────────────

echo "📦 Installing dependencies..."
pip install -r requirements.txt

echo "🗄️  Creating database & tables..."
python manage.py migrate

echo "👤 Creating superuser for admin panel..."
echo "   (Username: admin  Password: admin123)"
echo "from core.models import User; User.objects.filter(username='admin').exists() or User.objects.create_superuser('admin','admin@studynest.com','admin123')" | python manage.py shell

echo ""
echo "✅ Setup complete!"
echo ""
echo "🚀 Start the server:  python manage.py runserver"
echo "🌐 Open browser:      http://127.0.0.1:8000"
echo "⚙️  Admin panel:       http://127.0.0.1:8000/admin  (admin / admin123)"
echo ""
echo "🔐 Chat gate code:    1234"
echo "🔓 Message unlock:    5678"
