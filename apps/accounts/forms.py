from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from .models import User

class RegistrationForm(UserCreationForm):
    first_name = forms.CharField(label='الاسم', max_length=150)
    email = forms.EmailField(label='البريد الإلكتروني')
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].label = 'اسم المستخدم'
        self.fields['password1'].label = 'كلمة المرور'
        self.fields['password2'].label = 'تأكيد كلمة المرور'
    class Meta:
        model = User
        fields = ['first_name', 'username', 'email', 'password1', 'password2']

class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email']
        labels = {'first_name': 'الاسم', 'last_name': 'اسم العائلة', 'email': 'البريد الإلكتروني'}

class ArabicAuthenticationForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].label = 'اسم المستخدم'
        self.fields['password'].label = 'كلمة المرور'
