import json
from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST, require_GET
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.db.models import Q
from django.utils import timezone

from .models import User, FriendRequest, Message, Task, FocusSession


# ─── HELPERS ──────────────────────────────────────────────────────────────────
def json_body(request):
    try:
        return json.loads(request.body)
    except Exception:
        return {}


def ok(data=None):
    return JsonResponse({'ok': True, **(data or {})})


def err(msg, status=400):
    return JsonResponse({'ok': False, 'error': msg}, status=status)


COLORS = ['#c4512a', '#3a6494', '#4a6741', '#7a6494', '#c49a2a', '#6a8070', '#8b4563', '#2a7494']


# ─── PAGES ────────────────────────────────────────────────────────────────────
@ensure_csrf_cookie
def index(request):
    """Single page — shows login or app depending on session."""
    return render(request, 'index.html')


# ─── AUTH API ─────────────────────────────────────────────────────────────────
@csrf_exempt
@require_POST
def api_register(request):
    d = json_body(request)
    name     = (d.get('name') or '').strip()
    username = (d.get('username') or '').strip().lower()
    password = (d.get('password') or '').strip()

    if not name or not username or not password:
        return err('All fields are required.')
    if len(password) < 4:
        return err('Password must be at least 4 characters.')
    if User.objects.filter(username=username).exists():
        return err('Username already taken.')

    # pick colour based on user count
    count = User.objects.count()
    color = COLORS[count % len(COLORS)]

    parts = name.split(' ', 1)
    user = User(
        username   = username,
        first_name = parts[0],
        last_name  = parts[1] if len(parts) > 1 else '',
        color      = color,
    )
    user.set_password(password)
    user.save()  # student_id is auto-generated in save()

    login(request, user)
    return ok({'user': _user_dict(user)})


@csrf_exempt
@require_POST
def api_login(request):
    d = json_body(request)
    identifier = (d.get('username') or '').strip()
    password   = (d.get('password') or '').strip()

    # try username first, then student_id
    user = authenticate(request, username=identifier, password=password)
    if not user:
        try:
            u = User.objects.get(student_id=identifier)
            user = authenticate(request, username=u.username, password=password)
        except User.DoesNotExist:
            pass

    if not user:
        return err('Wrong username or password.')

    login(request, user)
    return ok({'user': _user_dict(user)})


@require_POST
def api_logout(request):
    logout(request)
    return ok()


def api_me(request):
    if not request.user.is_authenticated:
        return JsonResponse({'ok': False, 'authenticated': False})
    return ok({'user': _user_dict(request.user), 'authenticated': True})


def _user_dict(u):
    return {
        'id':         u.id,
        'student_id': u.student_id,
        'name':       u.get_full_name() or u.username,
        'username':   u.username,
        'color':      u.color,
    }


# ─── TASK API ─────────────────────────────────────────────────────────────────
@login_required
def api_tasks(request):
    if request.method == 'GET':
        tasks = Task.objects.filter(user=request.user).values('id', 'text', 'priority', 'done')
        return ok({'tasks': list(tasks)})

    if request.method == 'POST':
        d = json_body(request)
        text = (d.get('text') or '').strip()
        pri  = d.get('priority', 'm')
        if not text:
            return err('Task text is required.')
        t = Task.objects.create(user=request.user, text=text, priority=pri)
        return ok({'task': t.to_dict()})

    return err('Method not allowed.', 405)


@login_required
def api_task_detail(request, task_id):
    try:
        task = Task.objects.get(id=task_id, user=request.user)
    except Task.DoesNotExist:
        return err('Task not found.', 404)

    if request.method == 'PATCH':
        d = json_body(request)
        if 'done' in d:
            task.done = bool(d['done'])
        if 'text' in d:
            task.text = d['text']
        task.save()
        return ok({'task': task.to_dict()})

    if request.method == 'DELETE':
        task.delete()
        return ok()

    return err('Method not allowed.', 405)


# ─── FOCUS SESSION API ────────────────────────────────────────────────────────
@login_required
@require_POST
def api_session_complete(request):
    d = json_body(request)
    mode = d.get('mode', 'focus')
    mins = int(d.get('duration', 25))
    FocusSession.objects.create(user=request.user, mode=mode, duration_mins=mins)
    # Return today's stats
    today = timezone.now().date()
    sessions_today = FocusSession.objects.filter(user=request.user, completed_at__date=today)
    focus_mins = sum(s.duration_mins for s in sessions_today if s.mode == 'focus')
    return ok({
        'sessions_today': sessions_today.count(),
        'focus_mins':     focus_mins,
    })


# ─── USERNAME CHECK API ──────────────────────────────────────────────────────
def api_check_username(request):
    username = request.GET.get('username', '').strip().lower()
    if not username:
        return ok({'available': False})
    taken = User.objects.filter(username=username).exists()
    return ok({'available': not taken, 'username': username})


# ─── FRIEND / SEARCH API ──────────────────────────────────────────────────────
@login_required
def api_search_users(request):
    q = request.GET.get('q', '').strip().lower()
    if not q:
        return ok({'users': []})
    users = User.objects.filter(
        Q(username__icontains=q) | Q(student_id__icontains=q) |
        Q(first_name__icontains=q) | Q(last_name__icontains=q)
    ).exclude(id=request.user.id)[:10]

    result = []
    for u in users:
        rel = _get_relation(request.user, u)
        result.append({**_user_dict(u), 'relation': rel})
    return ok({'users': result})


def _get_relation(me, other):
    fr = FriendRequest.objects.filter(
        Q(sender=me, receiver=other) | Q(sender=other, receiver=me)
    ).first()
    if not fr:
        return 'none'
    if fr.status == 'accepted':
        return 'friend'
    if fr.status == 'pending' and fr.sender == me:
        return 'pending_sent'
    if fr.status == 'pending' and fr.receiver == me:
        return 'pending_recv'
    return 'none'


@login_required
@require_POST
def api_send_request(request):
    d = json_body(request)
    to_id = d.get('to_id')
    try:
        receiver = User.objects.get(id=to_id)
    except User.DoesNotExist:
        return err('User not found.')
    if receiver == request.user:
        return err('Cannot add yourself.')
    _, created = FriendRequest.objects.get_or_create(
        sender=request.user, receiver=receiver,
        defaults={'status': 'pending'}
    )
    return ok({'created': created})


@login_required
@require_POST
def api_respond_request(request):
    d = json_body(request)
    from_id = d.get('from_id')
    action  = d.get('action')  # 'accept' or 'reject'
    try:
        fr = FriendRequest.objects.get(sender_id=from_id, receiver=request.user, status='pending')
    except FriendRequest.DoesNotExist:
        return err('Request not found.')
    if action == 'accept':
        fr.status = 'accepted'
        fr.save()
    elif action == 'reject':
        fr.delete()
    return ok()


@login_required
def api_friends(request):
    accepted = FriendRequest.objects.filter(
        Q(sender=request.user) | Q(receiver=request.user),
        status='accepted'
    ).select_related('sender', 'receiver')
    friends = []
    for fr in accepted:
        friend = fr.receiver if fr.sender == request.user else fr.sender
        # last message preview
        last = Message.objects.filter(
            Q(sender=request.user, receiver=friend) |
            Q(sender=friend, receiver=request.user)
        ).order_by('-created_at').first()
        friends.append({
            **_user_dict(friend),
            'last_msg': last.text[:40] if last else '',
        })
    return ok({'friends': friends})


@login_required
def api_pending_requests(request):
    incoming = FriendRequest.objects.filter(
        receiver=request.user, status='pending'
    ).select_related('sender')
    return ok({'requests': [
        {**_user_dict(fr.sender), 'fr_id': fr.id} for fr in incoming
    ]})


# ─── MESSAGES API ─────────────────────────────────────────────────────────────
@login_required
def api_messages(request, peer_id):
    try:
        peer = User.objects.get(id=peer_id)
    except User.DoesNotExist:
        return err('User not found.')

    # Verify they are friends
    if _get_relation(request.user, peer) != 'friend':
        return err('Not friends.', 403)

    if request.method == 'GET':
        # Support polling: since= (timestamp ms) — returns messages newer than that ts
        since_ts = request.GET.get('since')
        msgs = Message.objects.filter(
            Q(sender=request.user, receiver=peer) |
            Q(sender=peer, receiver=request.user)
        )
        if since_ts:
            try:
                ts_ms = int(since_ts)
                if ts_ms > 0:
                    from datetime import datetime, timezone as tz
                    dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=tz.utc)
                    msgs = msgs.filter(created_at__gt=dt)
            except Exception:
                pass
        return ok({'messages': [m.to_dict(request.user.id) for m in msgs]})

    if request.method == 'POST':
        d = json_body(request)
        text = (d.get('text') or '').strip()
        if not text:
            return err('Message cannot be empty.')
        msg = Message.objects.create(sender=request.user, receiver=peer, text=text)
        return ok({'message': msg.to_dict(request.user.id)})

    return err('Method not allowed.', 405)


# ─── STATS API ────────────────────────────────────────────────────────────────
@login_required
def api_stats(request):
    today = timezone.now().date()
    sessions = FocusSession.objects.filter(user=request.user, completed_at__date=today)
    focus_mins  = sum(s.duration_mins for s in sessions if s.mode == 'focus')
    sess_count  = sessions.count()
    tasks_total = Task.objects.filter(user=request.user).count()
    tasks_done  = Task.objects.filter(user=request.user, done=True).count()
    return ok({
        'focus_mins':   focus_mins,
        'sessions':     sess_count,
        'tasks_total':  tasks_total,
        'tasks_done':   tasks_done,
    })
