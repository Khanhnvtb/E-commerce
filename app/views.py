from django.shortcuts import render, get_object_or_404, redirect
from .models import *
from django.db.models import F, FloatField, ExpressionWrapper, Sum, Value, CharField, Case, When
from django.db.models.functions import Coalesce, Round
from django.db.models import F, FloatField, ExpressionWrapper, Sum, Value, CharField, Count, Case, When
from django.db.models.functions import Coalesce, Round, TruncMonth
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.contrib.auth import authenticate, login, logout
from .serializers import ProductSerializer, FeedbackSerializer
from rest_framework.response import Response
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.pagination import PageNumberPagination
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
import locale
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from .forms import *
from django.core.paginator import Paginator
from django.db.models import Q
from django.forms import formset_factory
from datetime import datetime
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django.db.models.functions import Coalesce
from django.utils import timezone
from datetime import date
import os
from datetime import timedelta


def convert_diff(diff):
    days_in_month = 30
    days_in_year = 365
    if diff.days < 1:
        return f'{abs(int(diff.total_seconds() // 3600))} giờ'

    if diff.days < days_in_month:
        return f"{diff.days} ngày"

    elif diff.days < days_in_year:
        months = diff.days // days_in_month
        return f"{months} tháng"

    else:
        years = diff.days // days_in_year
        return f"{years} năm"


def log_in(request):
    if request.method == 'GET':
        return render(request, 'customer/login.html')
    else:
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            if user.is_superuser:
                return redirect('/admin_orders')
            return redirect('/home')
        else:
            return render(request, 'customer/login.html', {'error': 'Tên đăng nhập hoặc mật khẩu không đúng'})


def log_out(request):
    logout(request)
    return redirect('/home')


def register(request):
    if request.method == 'GET':
        return render(request, 'customer/home.html')
    else:
        username = request.POST.get('username')
        password = request.POST.get('password')
        repassword = request.POST.get('repassword')
        if password != repassword:
            message = 'Mật khẩu không khớp nhau'
        else:
            if User.objects.filter(username=username).exists():
                message = 'Tài khoản đã có người sử dụng'
            else:
                user = User(username=username)
                user.set_password(password)
                user.save()
                message = 'Đăng ký tài khoản thành công'
        return render(request, 'customer/login.html', {'messages': message})


def home(request):
    now = timezone.now()

    products = Product.objects.annotate(
        curr_price=Case(
            When(productsale__start_date__lte=now,
                 productsale__end_date__gte=now,
                 then=F('productsale__price')),
            default=F('price'),
            output_field=FloatField()
        ),
        discount_percent=Round(ExpressionWrapper(
            Coalesce((1 - F('curr_price') / F('price')) * 100, 0),
            output_field=FloatField()
        ), 0),
    )

    top_selling_products = products.order_by('-total_sold')[:10]

    top_sale_products = products.order_by('-discount_percent')[:10]

    hot_selling_product = (products.filter(orderitem__order__date__month=now.month,
                                           orderitem__order__date__year=now.year)
                           .annotate(total_sold_month=Sum('orderitem__quantity'))
                           .order_by('-total_sold_month')
                           )[:10]

    context = {
        'top_selling_products': top_selling_products,
        'top_sale_products': top_sale_products,
        'hot_selling_products': hot_selling_product,
        'range': range(10)
    }

    return render(request, 'customer/home.html', context)


def listProduct(request):
    categories = Category.objects.all()
    search = request.GET.get('search')

    context = {
        'categories': categories,
        'search': search
    }
    return render(request, 'customer/list-product.html', context)


@api_view(['GET'])
def getListProduct(request):
    search = request.GET.get('search')

    category = request.GET.get('category')
    if category:
        category = [int(category) for category in category.split(',')]

    status = request.GET.get('status')
    if status:
        status = [status for status in status.split(',')]

    min_price = request.GET.get('min_price')
    max_price = request.GET.get('max_price')
    rating = request.GET.get('rating')
    sort = request.GET.get('sort')
    top_sale_products = request.GET.get('top_sale_products')
    top_selling_products = request.GET.get('top_selling_products')
    best_selling_product = request.GET.get('best_selling_product')

    products = Product.objects.annotate(
        curr_price=Case(
            When(productsale__start_date__lte=timezone.now(),
                 productsale__end_date__gte=timezone.now(),
                 then=F('productsale__price')),
            default=F('price'),
            output_field=FloatField()
        ),
        discount_percent=Round(ExpressionWrapper(
            Coalesce((1 - F('curr_price') / F('price')) * 100, 0),
            output_field=FloatField()
        )),
        quantity=Sum('productdetail__quantity')
    )
    if search is not None and search != '':
        products = products.filter(name__icontains=search)

    if category:
        categories = Category.objects.filter(category_id__in=category)
        products = products.filter(category__in=categories)

    if status and len(status) == 1:
        if status[0] == 'instock':
            products = products.filter(quantity__gt=0)
        elif status[0] == 'outstock':
            products = products.filter(quantity=0)

    if min_price:
        products = products.filter(price__gte=int(min_price))

    if max_price:
        products = products.filter(price__lte=int(max_price))

    if rating:
        products = products.filter(rating__gte=rating)

    if top_sale_products:
        products = products.order_by('-discount_percent')

    if top_selling_products:
        products = products.order_by('-total_sold')

    if best_selling_product:
        now = timezone.now()
        products = (products.filter(
            orderitem__order__date__month=now.month,
            orderitem__order__date__year=now.year
        ).annotate(
            total_sold_month=Sum('orderitem__quantity')
        ).order_by('-total_sold_month')
                    )
    if sort == 'price_asc':
        products = products.order_by('curr_price')
    elif sort == 'price_desc':
        products = products.order_by('-curr_price')

    paginator = PageNumberPagination()
    paginator.page_query_param = 'page'
    paginator.page_size = 20
    result_page = paginator.paginate_queryset(products, request)
    serializer = ProductSerializer(result_page, many=True, context={'request': request})

    respone = paginator.get_paginated_response(serializer.data)
    respone.data['current_page'] = paginator.page.number
    respone.data['total_page'] = paginator.page.paginator.num_pages
    return respone


def getProductDetail(request, product_id):
    product = Product.objects.filter(pk=product_id).annotate(
        curr_price=Case(
            When(productsale__start_date__lte=timezone.now(),
                 productsale__end_date__gte=timezone.now(),
                 then=F('productsale__price')),
            default=F('price'),
            output_field=FloatField()
        ),
        discount_percent=Round(ExpressionWrapper(
            Coalesce((1 - F('curr_price') / F('price')) * 100, 0),
            output_field=FloatField()
        )),
        quantity=Sum('productdetail__quantity')
    ).first()

    sales = product.productsale_set.filter(start_date__lte=timezone.now(), end_date__gte=timezone.now()).first()
    feedbacks = Feedback.objects.filter(product=product).order_by('-date')
    num_feedbacks = feedbacks.count()
    feedback_paginator = Paginator(feedbacks, 5)
    feedback_page = request.GET.get('page')
    feedbacks = feedback_paginator.get_page(feedback_page)

    related_products = (Product.objects
                        .filter(category=product.category)
                        .exclude(pk=product.pk)
                        )[:10].annotate(
        curr_price=Case(
            When(productsale__start_date__lte=timezone.now(),
                 productsale__end_date__gte=timezone.now(),
                 then=F('productsale__price')),
            default=F('price'),
            output_field=FloatField()
        ),
        discount_percent=Round(ExpressionWrapper(
            Coalesce((1 - F('curr_price') / F('price')) * 100, 0),
            output_field=FloatField()
        ))
    )

    context = {
        'product': product,
        'sales': sales,
        'num_feedbacks': num_feedbacks,
        'feedbacks': feedbacks,
        'related_products': related_products
    }
    return render(request, 'customer/product_detail.html', context)


@login_required(login_url='/login')
@api_view(['GET', 'POST', 'PUT', 'DELETE'])
def add_to_cart(request):
    if request.method == 'GET':
        cart = Cart.objects.filter(customer=request.user).last()
        if not cart:
            cart = Cart.objects.create(customer=request.user)
        cartitems = CartItem.objects.filter(cart=cart)
        cartitems = cartitems.annotate(
            price=Case(
                When(product__productsale__start_date__lte=timezone.now(),
                     product__productsale__end_date__gte=timezone.now(),
                     then=F('product__productsale__price')),
                default=F('product__price'),
                output_field=FloatField()
            ),
            total_price=Round(ExpressionWrapper(F('price') * F('quantity'), output_field=FloatField())
                              ))
        voucher_wallet = VoucherWallet.objects.filter(customer=request.user).first()
        if voucher_wallet:
            voucher_wallet = VoucherWallet.objects.create(customer=request.user)
            voucher_wallet.save()

        coupons = Coupon.objects.filter(start_date__lte=timezone.now(),
                                         end_date__gte=timezone.now()).order_by('discount')  
        context = {
            'cart': cart,
            'cartitems': cartitems,
            'voucher_wallet': voucher_wallet,
            'coupons': coupons
        }
        return render(request, 'customer/cart.html', context=context)

    if request.method == 'POST':
        id = request.POST.get('product_id')
        product = get_object_or_404(Product, pk=id)

        color = request.POST.get('color')
        size = request.POST.get('size')
        quantity = request.POST.get('quantity')
        quantity = int(quantity)
        cart = Cart.objects.filter(customer=request.user).last()
        if not cart:
            cart = Cart.objects.create(customer=request.user)

        cart_item = CartItem.objects.filter(cart=cart, product=product, color=color, size=size).first()
        product_detail = ProductDetail.objects.filter(product=product, color=color, size=size).first()
        if cart_item:
            if cart_item.quantity + quantity > product_detail.quantity:
                return JsonResponse({'status': 'error',
                                     'message': 'Số lượng sản phẩm không đủ, trong giỏ hàng đã có ' + str(
                                         cart_item.quantity) + ' sản phẩm'})
        else:
            cart_item = CartItem.objects.create(cart=cart, product=product, color=color, size=size, quantity=quantity)
        cart_item.save()
        num_cart_item = cart.cartitem_set.count()
        return JsonResponse(
            {'status': 'success', 'message': 'Thêm vào giỏ hàng thành công', 'num_cart_item': num_cart_item})


def edit_cart_item(request):
    cart_item_id = request.POST.get('cart_item_id')
    quantity = request.POST.get('quantity')
    cart_item = CartItem.objects.get(pk=cart_item_id)
    product_detail = ProductDetail.objects.filter(product=cart_item.product, color=cart_item.color,
                                                  size=cart_item.size).first()
    if int(quantity) > product_detail.quantity:
        return JsonResponse({'status': 'error', 'message': 'Số lượng sản phẩm không đủ'})
    cart_item.quantity = int(quantity)
    cart_item.save()
    if int(quantity) == 0:
        cart_item.delete()
    return JsonResponse({'status': 'success', 'message': 'Cập nhật thành công'})


def delete_cart_item(request):
    cart_item_id = request.POST.get('cart_item_id')
    cart_item = CartItem.objects.get(pk=cart_item_id)
    cart_item.delete()
    return JsonResponse({'success': 'Xóa thành công'})


@api_view(['GET'])
def check_coupon(request):
    coupon_code = request.GET.get('coupon')
    coupon = Coupon.objects.filter(code=coupon_code).order_by('-start_date').first()
    if not coupon:
        return JsonResponse({'status': 'error', 'message': 'Mã giảm giá không hợp lệ'})

    now = timezone.now()
    if now < coupon.start_date or now > coupon.end_date:
        return JsonResponse({'status': 'error', 'message': 'Mã giảm giá đã hết hạn'})

    total_money = request.GET.get('total_money')
    total_money = float(total_money)
    if total_money < coupon.condition:
        locale.setlocale(locale.LC_ALL, 'vi_VN.UTF-8')
        condition = locale.format_string('%dđ', int(coupon.condition), grouping=True).replace(',', '.')
        return JsonResponse(
            {'status': 'error', 'message': 'Chưa đủ điều kiện đơn hàng tối thiếu. Đơn hàng tối thiểu là ' + condition})

    return JsonResponse({'status': 'success', 'discount': coupon.discount, 'condition': coupon.condition})


def checkout(request):
    if request.method == 'GET':
        return render(request, 'customer/checkout.html')

    cart_items = request.POST.getlist('cart_item')
    cart_items = [int(cart_item) for cart_item in cart_items]

    total = request.POST.get('total_money')
    coupon = request.POST.get('coupon')
    discount = request.POST.get('discount')

    cart_items = CartItem.objects.filter(pk__in=cart_items).annotate(
        price=Case(
            When(product__productsale__start_date__lte=timezone.now(),
                 product__productsale__end_date__gte=timezone.now(),
                 then=F('product__productsale__price')),
            default=F('product__price'),
            output_field=FloatField()
        ),
    )
    locale.setlocale(locale.LC_ALL, 'vi_VN.UTF-8')
    total = locale.format_string('%dđ', int(total), grouping=True).replace(',', '.')
    coupons = Coupon.objects.filter(start_date__lte=timezone.now(), end_date__gte=timezone.now()).order_by('discount')
    context = {
        'cart_items': cart_items,
        'total': total,
        'coupon': coupon,
        'discount': discount,
        'coupons': coupons
    }
    return render(request, 'customer/checkout.html', context)


def buy_now(request):
    if request.method == 'POST':
        product_id = request.POST.get('product_id')
        product = Product.objects.filter(pk=product_id).annotate(
            curr_price=Case(
                When(productsale__start_date__lte=timezone.now(),
                     productsale__end_date__gte=timezone.now(),
                     then=F('productsale__price')),
                default=F('price'),
                output_field=FloatField()
            ),
            discount_percent=Round(ExpressionWrapper(
                Coalesce((1 - F('curr_price') / F('price')) * 100, 0),
                output_field=FloatField()
            ), 0),
        ).first()

        color = request.POST.get('color')
        size = request.POST.get('size')
        quantity = request.POST.get('quantity')
        quantity = int(quantity)

        product_detail = ProductDetail.objects.filter(product=product, color=color, size=size).first()
        if quantity > product_detail.quantity:
            return JsonResponse({'status': 'error', 'message': 'Số lượng sản phẩm không đủ'})
        total = product.curr_price * quantity
        locale.setlocale(locale.LC_ALL, 'vi_VN.UTF-8')
        total = locale.format_string('%dđ', int(total), grouping=True).replace(',', '.')
        coupons = Coupon.objects.filter(start_date__lte=timezone.now(), end_date__gte=timezone.now()).order_by('discount')

        context = {
            'product': product,
            'color': color,
            'size': size,
            'quantity': quantity,
            'total': total,
            'coupons': coupons
        }
        return render(request, 'customer/checkout.html', context)


def add_address(request):
    if request.method == 'POST':
        user = request.user
        form = AddressShippingForm(request.POST)
        if not form.is_valid():
            return JsonResponse({'status': 'error', 'message': 'Thông tin không hợp lệ'})
        receiver = form.cleaned_data['receiver']
        phone = form.cleaned_data['phone']
        address = form.cleaned_data['address']
        address_shipping = AddressShipping(receiver=receiver, phone=phone, address=address, customer=user)
        address_shipping.save()
        data = {
            'status': 'success',
            'result': {
                'id': address_shipping.address_shipping_id,
                'receiver': receiver,
                'phone': phone,
                'address': address
            }
        }
        return JsonResponse(data)


def order(request):
    if request.method == 'POST':
        coupon = request.POST.get('coupon')
        discount = request.POST.get('discount')
        cart_items = request.POST.getlist('cart_item')
        cart_items = CartItem.objects.filter(pk__in=cart_items)
        order_form = OrderForm(request.POST)
        product_id = request.POST.get('product_id')
        size = request.POST.get('size')
        color = request.POST.get('color')
        quantity = request.POST.get('quantity')
        if quantity:
            quantity = int(request.POST.get('quantity'))

        if order_form.is_valid():
            order = order_form.save(commit=False)
            order.customer = request.user
            status = OrderStatus.objects.get(name='Chờ xác nhận')
            order.status = status
            order.save()
            tracking = Tracking.objects.create(order_status=status, order=order)
            tracking.save()
            coupon = Coupon.objects.filter(code=coupon).order_by('-start_date').first()

            if coupon:
                coupon.quantity -= 1
                coupon.save()
            for cart_item in cart_items:
                order_item = OrderItem.objects.create(
                    size=cart_item.size,
                    color=cart_item.color,
                    quantity=cart_item.quantity,
                    price=cart_item.product.price,
                    order=order,
                    product=cart_item.product
                )
                order_item.save()

                product = cart_item.product
                product.total_sold += cart_item.quantity
                product.save()

                product_detail = ProductDetail.objects.filter(product=product, color=cart_item.color,
                                                              size=cart_item.size).first()
                if product_detail.quantity < cart_item.quantity:
                    raise ValidationError('Sản phẩm đã hết hàng')
                product_detail.quantity -= cart_item.quantity
                product_detail.save()

                cart_item.delete()
            if product_id:
                product = Product.objects.filter(pk=product_id).annotate(
                    curr_price=Case(
                        When(productsale__start_date__lte=timezone.now(),
                             productsale__end_date__gte=timezone.now(),
                             then=F('productsale__price')),
                        default=F('price'),
                        output_field=FloatField()
                    ),
                ).first()
                product_detail = ProductDetail.objects.filter(product=product, color=color, size=size).first()
                if product_detail.quantity < quantity:
                    raise ValidationError('Sản phẩm đã hết hàng')
                product_detail.quantity -= quantity
                product_detail.save()

                product.total_sold += quantity
                product.save()
                order_item = OrderItem.objects.create(
                    size=size,
                    color=color,
                    quantity=quantity,
                    price=product.curr_price,
                    order=order,
                    product=product
                )
                order_item.save()
            return render(request, 'customer/success-order.html')
        else:
            context = {
                'cart_items': cart_items,
                'coupon': coupon,
                'discount': discount,
                'order_form': order_form,
            }
            return render(request, 'customer/checkout.html', context)
    return redirect('home')


@login_required(login_url='/login')
def get_order(request):
    keyword = request.GET.get('keyword', '')
    status_choice = request.GET.get('status', '')
    start_date = request.GET.get('start_date', '')
    end_date = request.GET.get('end_date', '')

    orders = Order.objects.filter(customer=request.user).order_by('-order_id')
    if keyword:
        orders = orders.filter(order_id__icontains=keyword)
    if status_choice:
        orders = orders.filter(status__name=status_choice)
    if start_date:
        orders = orders.filter(date__gte=start_date)
    if end_date:
        orders = orders.filter(date__lte=end_date)

    paginator = Paginator(orders, 10)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)
    status = OrderStatus.objects.all()

    context = {
        'page_obj': page_obj,
        'orders' : page_obj.object_list,
        'states': status
    }
    return render(request, 'customer/orders.html', context)


def get_order_detail(request):
    order_id = int(request.GET.get('order_id'))
    order = get_object_or_404(Order, pk=order_id)
    order_tracking = Tracking.objects.filter(order=order).order_by('date')
    context = {
        'order': order,
        'order_tracking': order_tracking
    }
    return render(request, 'customer/order_detail.html', context)


def cancel_order(request):
    order_id = request.GET.get('order_id')
    order = Order.objects.get(pk=order_id)
    order.status = OrderStatus.objects.get(name='Hủy đơn')
    order_item = order.orderitem_set.all()
    for item in order_item:
        product_detail = ProductDetail.objects.filter(product=item.product, color=item.color, size=item.size).first()
        product_detail.quantity += item.quantity
        product_detail.save()
    order.save()
    context = {
        'order': order,
    }
    return render(request, 'customer/order_detail.html', context)


def handleFeedback(request):
    if request.method == 'GET':
        order_id = request.GET.get('order_id')
        order = Order.objects.get(pk=order_id)
        context = {
            'order': order
        }

    if request.method == 'POST':
        orderitem_id = request.POST.get('order_item_id')
        orderitem = OrderItem.objects.get(pk=orderitem_id)
        product = orderitem.product
        comment = request.POST.get('comment')
        rating = request.POST.get('rating')
        images = request.FILES.getlist('images')
        feedback = Feedback.objects.create(
            comment=comment,
            rating=rating,
            product=product,
            customer=request.user
        )
        feedback.save()
        for image in images:
            feedback_image = FeedbackImage(name=image, feedback=feedback)
            feedback_image.save()
        orderitem.feedback = feedback
        orderitem.save()

        order = orderitem.order
        context = {
            'order': order
        }

    return render(request, 'customer/feedback.html', context)


@login_required(login_url='/login')
def getFeedback(request):
    feedbacks = Feedback.objects.filter(customer=request.user).order_by('-date')
    paginator = Paginator(feedbacks, 10)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'feedbacks': page_obj.object_list
    }
    return render(request, 'customer/list-feedback.html', context)


@api_view(['GET'])
def getFeedbackByProduct(request):
    product_id = int(request.GET.get('product_id'))
    product = Product.objects.get(pk=product_id)
    feedbacks = Feedback.objects.filter(product=product).order_by('-date')
    paginator = PageNumberPagination()
    paginator.page_query_param = 'page'
    paginator.page_size = 5
    result_page = paginator.paginate_queryset(feedbacks, request)
    serializer = FeedbackSerializer(result_page, many=True, context={'request': request})

    respone = paginator.get_paginated_response(serializer.data)
    respone.data['current_page'] = paginator.page.number
    respone.data['total_page'] = paginator.page.paginator.num_pages
    return respone


def getCoupon(request):
    coupons = Coupon.objects.filter(start_date__lte=timezone.now(), end_date__gte=timezone.now()).order_by(
        '-start_date')
    paginator = Paginator(coupons, 10)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)
    context = {
        'page_obj': page_obj,
        'coupons': page_obj.object_list
    }
    return render(request, 'customer/list-coupon.html', context)


def profile(request):
    user = request.user
    created_at = user.date_joined
    day_created = timezone.now() - created_at
    day_created = convert_diff(day_created) + ' trước'
    last_order = Order.objects.filter(customer=user).last()
    if last_order:
        day_last_order = timezone.now() - last_order.date
        day_last_order = convert_diff(day_last_order)
        day_last_order += ' trước'
    else:
        day_last_order = 'Chưa đặt hàng'
    order = Order.objects.filter(customer=user, status__name='Giao hàng thành công')
    total_order = order.count()
    total_money = order.aggregate(total_money=Sum('total', default=0))['total_money']
    context = {
        'user': user,
        'day_created': day_created,
        'day_last_order': day_last_order,
        'total_order': total_order,
        'total_money': total_money
    }

    if request.method == 'POST':
        form = UserForm(request.POST, instance=request.user)
        if form.is_valid():
            user = form.save()
        context['form'] = form
    return render(request, 'customer/profile.html', context)


def notification(request):
    return render(request, 'customer/notification.html')


@login_required(login_url='/login')
def addProduct(request):
    error = ''
    product_form = ProductForm(request.POST or None)
    product_sale_form = ProductSaleForm(request.POST or None)
    colors = request.POST.getlist('color')
    sizes = request.POST.getlist('size')
    quantities = request.POST.getlist('quantity')
    product_image_form = ProductImageForm(request.POST, request.FILES)
    if product_form.is_valid() and product_sale_form.is_valid() and product_image_form.is_valid():
        product = product_form.save()
        product_sale = ProductSale(price=product_sale_form.cleaned_data['price'], product=product)
        product_sale.save()
        for i in range(len(colors)):
            product_detail = ProductDetail(color=colors[i], size=sizes[i], quantity=quantities[i], product=product)
            product_detail.save()
            images = request.FILES.getlist('name')
            for image in images:
                product_image = ProductImage(name=image, product=product)
                product_image.save()
    else:
        error = 'Bạn cần nhập đầy đủ thông tin'
    return render(request, 'admin_shop/add-product.html',
                  {'product_form': product_form, 'product_sale_form': product_sale_form,
                   'product_image_form': product_image_form, 'error': error})


@login_required(login_url='/login')
def addCoupon(request):
    error = ''
    if request.method == "POST":
        coupon_form = CouponForm(request.POST)
        if coupon_form.is_valid():
            coupon_form.save()
            coupon_form = Coupon()
        else:
            error = 'Mã giảm giá đã tồn tại trong hệ thống'
    else:
        coupon_form = CouponForm()
    return render(request, 'admin_shop/add-coupon.html', {'coupon_form': coupon_form, 'error': error})


@login_required(login_url='/login')
def couponManager(request):
    keyword = request.GET.get('keyword', '')
    coupons = Coupon.objects.filter(code__contains=keyword)
    if request.method == "POST":
        start_date = request.POST.get('start_date', '')
        end_date = request.POST.get('end_date', '')
        if start_date == '' and end_date == '':
            coupons = coupons.all()
        elif end_date == '':
            coupons = coupons.filter(start_date__gte=start_date)
        elif start_date == '':
            coupons = coupons.filter(end_date__lte=end_date)
        else:
            coupons = coupons.filter(Q(start_date__gte=start_date) & Q(end_date__lte=end_date))

    paginator = Paginator(coupons, 15)

    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)
    return render(request, 'admin_shop/coupons.html', {'page_obj': page_obj})


@login_required(login_url='/login')
def productManager(request):
    categories = Category.objects.all()
    if request.method == "POST":
        keyword = request.POST.get('keyword', '')
        products = Product.objects.filter(name__contains=keyword).annotate(
            total_quantity=Sum('productdetail__quantity'))
        category = request.POST.get('category')
        status = request.POST.get('status')
        if category:
            products = products.filter(category__name=category)
        if status:
            if status == 'Còn hàng':
                products = products.filter(total_quantity__gt=0)
            else:
                products = products.filter(total_quantity=0)
    else:
        keyword = request.GET.get('keyword', '')
        products = Product.objects.filter(name__contains=keyword).annotate(
            total_quantity=Sum('productdetail__quantity'))
    paginator = Paginator(products, 15)

    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)
    return render(request, 'admin_shop/products.html', {'page_obj': page_obj, 'categories': categories})


@login_required(login_url='/login')
def getProductDetailAdmin(request):
    if request.method == "POST":
        feedback_id = int(request.GET.get('feedback_id'))
        response_form = ResponseForm(request.POST)
        if response_form.is_valid():
            text = response_form.cleaned_data.get("textfield")
            response = FeedbackRespone(comment=text, feedback_id=feedback_id)
            response.save()

    product_id = int(request.GET.get('product_id'))
    product = Product.objects.filter(pk=product_id).annotate(
        curr_price=Case(
            When(productsale__start_date__lte=timezone.now(),
                 productsale__end_date__gte=timezone.now(),
                 then=F('productsale__price')),
            default=F('price'),
            output_field=FloatField()
        ),
    ).first()

    feedback = Feedback.objects.filter(product=product).order_by('-date')
    feedback_paginator = Paginator(feedback, 5)
    feedback_page = request.GET.get('page')
    page_obj = feedback_paginator.get_page(feedback_page)
    feedbacks = page_obj.object_list
    response_form = ResponseForm()
    context = {
        'product': product,
        'feedbacks': feedbacks,
        'page_obj': page_obj,
        'response_form': response_form
    }

    return render(request, 'admin_shop/product-detail.html', context)


@login_required(login_url='/login')
def customerManager(request):
    keyword = request.GET.get('keyword', '')
    customers = User.objects.filter(name__contains=keyword, is_superuser=0, order__status=7).annotate(
        total_orders=Count('order'),
        total_amount=Coalesce(Sum('order__total'), Value(0.0)),
        type_customer=Case(
            When(total_amount__gte=20000000, then=Value('VIP3')),
            When(total_amount__gte=10000000, then=Value('VIP2')),
            When(total_amount__gte=5000000, then=Value('VIP1')),
            default=Value('Thường')
        )
    )
    if request.method == "POST":
        type_customer = request.POST.get('type_customer', 'Tất cả')
        if type_customer != 'Tất cả':
            customers = customers.filter(type_customer=type_customer)

    paginator = Paginator(customers, 15)

    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)
    return render(request, 'admin_shop/customers.html', {'page_obj': page_obj})


@login_required(login_url='/login')
def orderManager(request):
    states = OrderStatus.objects.all()
    keyword = request.GET.get('keyword', '')
    orders = Order.objects.filter(customer__name__contains=keyword).select_related('customer', 'status').order_by(
        '-order_id')
    if request.method == "POST":
        status = request.POST.get('status', '')
        start_date = request.POST.get('start_date', '')
        end_date = request.POST.get('end_date', '')
        if status:
            orders = orders.filter(status__name=status)
        if start_date == '' and end_date == '':
            orders = orders.all()
        elif end_date == '':
            orders = orders.filter(date__gte=start_date)
        elif start_date == '':
            orders = orders.filter(date__lte=end_date)
        else:
            orders = orders.filter(Q(date__gte=start_date) & Q(date__lte=end_date))

    paginator = Paginator(orders, 15)

    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)
    return render(request, 'admin_shop/orders.html', {'page_obj': page_obj, 'states': states})


@login_required(login_url='/login')
def getOrderDetail(request):
    order_id = int(request.GET.get("order_id"))
    order = Order.objects.filter(order_id=order_id).select_related('customer', 'status').first()
    total_price = order.total - order.discount + order.shipping
    order_items = OrderItem.objects.filter(order_id=order_id).annotate(
        curr_price=Case(When(product__productsale__start_date__lte=timezone.now(),
                             product__productsale__end_date__gte=timezone.now(),
                             then=F('product__productsale__price')), default=F('product__price')),
        total=F('curr_price') * F('quantity'))
    if request.method == "POST":
        status = int(request.POST.get('status'))
        if order.status.order_status_id != status:
            status = OrderStatus.objects.get(order_status_id=status)
            order.status = status
            order.save()
            tracking = Tracking(order=order, order_status=status)
            tracking.save()
        else:
            pass
    if order.status.order_status_id == 1:
        status_ids = [1, 3, 6]
    elif order.status.order_status_id < 5:
        status_ids = [order.status.order_status_id, order.status.order_status_id + 1, 6]
    elif order.status.order_status_id == 5:
        status_ids = [5, 6, 7]
    elif order.status.order_status_id == 6:
        status_ids = [6]
    else:
        status_ids = [7]
    states = OrderStatus.objects.filter(order_status_id__in=status_ids).order_by("order_status_id")
    return render(request, 'admin_shop/order-detail.html',
                  {'order': order, 'order_items': order_items, 'states': states, 'total_price': total_price, })


@login_required(login_url='/login')
def report(request):
    if request.method == "POST":
        columns = []
        values = []
        type_report = request.POST.get('type_report', 1)
        start_date = request.POST.get('start_date', '')
        end_date = request.POST.get('end_date', '')
        if start_date == '':
            start_date = timezone.datetime(2020, 1, 1)
        if end_date == '':
            end_date = timezone.datetime(2050, 12, 31)
        if type_report == '1':
            report = Order.objects.filter(date__gte=start_date, date__lte=end_date).annotate(
                month=TruncMonth('date')).values('month').annotate(revenue=Sum('total')).values(
                'month', 'revenue').order_by('month')
            for record in report:
                record['month'] = record['month'].strftime('%m %Y').split()
                record['month'] = 'Tháng ' + record['month'][0] + ' năm ' + record['month'][1]
                columns.append(record['month'])
                values.append(int(record['revenue']))
            report_name = 'Báo cáo doanh thu theo tháng'
        elif type_report == '2':
            report = Order.objects.filter(date__gte=start_date, date__lte=end_date, status_id=7).annotate(
                month=TruncMonth('date')).values('month').annotate(order_total=Count('order_id')).values(
                'month', 'order_total').order_by('month')
            for record in report:
                record['month'] = record['month'].strftime('%m %Y').split()
                record['month'] = 'Tháng ' + record['month'][0] + ' năm ' + record['month'][1]
                columns.append(record['month'])
                values.append(record['order_total'])
            report_name = 'Báo cáo đơn hàng'
        else:
            report = Order.objects.filter(date__gte=start_date, date__lte=end_date, status_id=7).select_related(
                'customer').values('customer__name').annotate(total=Sum('total')).order_by('total')
            for record in report:
                columns.append(record['customer__name'])
                values.append(record['total'])
            report_name = 'Báo cáo khách hàng'
        return render(request, 'admin_shop/report.html',
                      {'values': values, 'columns': columns, 'report_name': report_name})
    else:
        return render(request, 'admin_shop/report.html')


@login_required(login_url='/login')
def deleteProduct(request):
    product_id = int(request.GET.get('product_id'))
    product = Product.objects.get(product_id=product_id)
    images = ProductImage.objects.filter(product=product).values('name')
    for image in images:
        os.remove(f"app/media/{image['name']}")
    product.delete()
    products = Product.objects.all()
    categories = Category.objects.all()

    paginator = Paginator(products, 15)

    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)
    return redirect('/products', {'page_obj': page_obj, 'categories': categories})


@login_required(login_url='/login')
def viewProfile(request):
    user_id = int(request.GET.get('user_id'))
    if request.user.is_superuser == 1:
        user = User.objects.get(id=user_id)
        diff = date.today() - user.date_joined.date()
        time = convert_diff(diff)

        if user_id != 1:
            last_order = Order.objects.filter(customer=user).last()
            day_last_order = timezone.now() - last_order.date
            day_last_order = convert_diff(day_last_order)

            total_order = Order.objects.filter(customer=user).count()
            total_money = Order.objects.filter(customer=user, status__name='Giao hàng thành công').aggregate(
                total_money=Sum('total'))['total_money']
            context = {
                'user': user,
                'day_last_order': day_last_order,
                'total_order': total_order,
                'total_money': total_money,
                'time': time
            }
        else:
            context = {
                'user': user,
                'time': time
            }
    else:
        return redirect('/home')
    return render(request, 'admin_shop/profile.html', context=context)
