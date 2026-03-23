import os
import shutil
import tempfile
import unittest
from unittest.mock import patch, MagicMock
import sys

current_script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_script_dir)
common_path = os.path.join(project_root, 'common')

if common_path not in sys.path:
    sys.path.insert(0, common_path)
if project_root not in sys.path:
     sys.path.insert(0, project_root)

from common.interfaces.framework_analyzer import FrameworkAnalyzer
from django_analyzer import DjangoAnalyzer
from common.interfaces.code_analyzer import CodeAnalyzer
from python_analyzer import PythonCodeAnalyzer

class TestPythonCodeAnalyzer(unittest.TestCase):
    
    def setUp(self):
        """Set up test environment with a temporary directory and sample files."""
        # Create a temporary directory
        self.test_dir = tempfile.mkdtemp()
        
        # Create basic project structure
        self.project_root = os.path.join(self.test_dir, "test_project")
        os.makedirs(self.project_root)
        
        # Create output directory
        self.output_dir = os.path.join(self.test_dir, "output")
        os.makedirs(self.output_dir)
        
        # Create sample files
        self._create_sample_project()
        
        # Initialize analyzer
        self.analyzer = PythonCodeAnalyzer()
    
    def tearDown(self):
        """Clean up the temporary directory."""
        shutil.rmtree(self.test_dir)
    
    def _create_sample_project(self):
        """Create a sample Django-like project structure with test files."""
        # Create project structure
        os.makedirs(os.path.join(self.project_root, "myapp"))
        os.makedirs(os.path.join(self.project_root, "myapp", "migrations"))
        
        # Create manage.py
        with open(os.path.join(self.project_root, "manage.py"), "w") as f:
            f.write("""#!/usr/bin/env python
import os
import sys

if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "test_project.settings")
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)
""")
        
        # Create settings.py
        os.makedirs(os.path.join(self.project_root, "test_project"))
        with open(os.path.join(self.project_root, "test_project", "settings.py"), "w") as f:
            f.write("""
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SECRET_KEY = 'test-key'
DEBUG = True
ALLOWED_HOSTS = []

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'myapp',
]

ROOT_URLCONF = 'test_project.urls'
""")
        
        # Create urls.py
        with open(os.path.join(self.project_root, "test_project", "urls.py"), "w") as f:
            f.write("""
from django.urls import include, path
from django.contrib import admin

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('myapp.urls')),
]
""")
        
        # Create app urls.py
        with open(os.path.join(self.project_root, "myapp", "urls.py"), "w") as f:
            f.write("""
from django.urls import path
from rest_framework.routers import DefaultRouter
from myapp import views

router = DefaultRouter()
router.register(r'users', views.UserViewSet)
router.register(r'groups', views.GroupViewSet)

urlpatterns = router.urls
""")
        
        # Create models.py
        with open(os.path.join(self.project_root, "myapp", "models.py"), "w") as f:
            f.write("""
from django.db import models

class Category(models.Model):
    name = models.CharField(max_length=100)
    
    class Meta:
        verbose_name_plural = 'categories'
    
    def __str__(self):
        return self.name

class Item(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='items')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return self.name
    
    def get_absolute_url(self):
        return f"/items/{self.id}/"
""")
        
        # Create serializers.py
        with open(os.path.join(self.project_root, "myapp", "serializers.py"), "w") as f:
            f.write("""
from rest_framework import serializers
from myapp.models import Category, Item
from django.contrib.auth.models import User, Group

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'groups']

class GroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = Group
        fields = ['id', 'name']

class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ['id', 'name']

class ItemSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    category_id = serializers.IntegerField(write_only=True)
    
    class Meta:
        model = Item
        fields = ['id', 'name', 'description', 'price', 'category', 'category_id', 'created_at', 'updated_at']
        read_only_fields = ['created_at', 'updated_at']
    
    def validate_price(self, value):
        if value <= 0:
            raise serializers.ValidationError("Price must be greater than zero")
        return value
""")
        
        # Create views.py
        with open(os.path.join(self.project_root, "myapp", "views.py"), "w") as f:
            f.write("""
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from django.contrib.auth.models import User, Group
from myapp.models import Category, Item
from myapp.serializers import UserSerializer, GroupSerializer, CategorySerializer, ItemSerializer

class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer

class GroupViewSet(viewsets.ModelViewSet):
    queryset = Group.objects.all()
    serializer_class = GroupSerializer

class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer

class ItemViewSet(viewsets.ModelViewSet):
    queryset = Item.objects.all()
    serializer_class = ItemSerializer
    
    @action(detail=True, methods=['post'])
    def discount(self, request, pk=None):
        item = self.get_object()
        discount = float(request.data.get('discount', 0))
        if discount > 0:
            item.price = item.price * (1 - discount/100)
            item.save()
        serializer = self.get_serializer(item)
        return Response(serializer.data)
""")
        
        # Create __init__.py files
        open(os.path.join(self.project_root, "test_project", "__init__.py"), "w").close()
        open(os.path.join(self.project_root, "myapp", "__init__.py"), "w").close()
        open(os.path.join(self.project_root, "myapp", "migrations", "__init__.py"), "w").close()
        
        # Create external module
        os.makedirs(os.path.join(self.project_root, "external_lib"))
        with open(os.path.join(self.project_root, "external_lib", "utils.py"), "w") as f:
            f.write("""
def calculate_tax(price, tax_rate=0.1):
    return price * tax_rate

class PriceCalculator:
    def __init__(self, base_price):
        self.base_price = base_price
    
    def apply_discount(self, discount_percent):
        return self.base_price * (1 - discount_percent/100)
    
    def calculate_final_price(self, discount_percent=0, tax_rate=0.1):
        discounted_price = self.apply_discount(discount_percent)
        return discounted_price + (discounted_price * tax_rate)
""")
        open(os.path.join(self.project_root, "external_lib", "__init__.py"), "w").close()

    def test_analyze_file_basic(self):
        """Test basic file analysis functionality."""
        file_path = os.path.join(self.project_root, "myapp", "models.py")
        result = self.analyzer.analyze_file(file_path)
        
        # Check that classes were detected
        self.assertIn("Category", result["classes"])
        self.assertIn("Item", result["classes"])
        
        # Check class attributes
        category_class = result["classes"]["Category"]
        self.assertEqual(category_class["name"], "Category")
        self.assertIn("Meta", [inner["name"] for inner in category_class["innerClasses"]])
        
        # Check methods
        item_class = result["classes"]["Item"]
        self.assertIn("get_absolute_url", item_class["functions"])
        
        # Verify function details
        get_url_func = item_class["functions"]["get_absolute_url"]
        self.assertEqual(get_url_func["context"]["name"], "get_absolute_url")
    
    def test_analyze_file_serializers(self):
        """Test analysis of serializer file."""
        file_path = os.path.join(self.project_root, "myapp", "serializers.py")
        result = self.analyzer.analyze_file(file_path)
        
        # Check that all serializers were detected
        self.assertIn("UserSerializer", result["classes"])
        self.assertIn("GroupSerializer", result["classes"])
        self.assertIn("CategorySerializer", result["classes"])
        self.assertIn("ItemSerializer", result["classes"])
        
        # Check detailed serializer structure
        item_serializer = result["classes"]["ItemSerializer"]
        
        # Verify parent classes (should include ModelSerializer)
        self.assertTrue(any("ModelSerializer" in parent for parent in item_serializer["parentClasses"]))
        
        # Check for validation method
        self.assertIn("validate_price", item_serializer["functions"])
    
    def test_analyze_file_views(self):
        """Test analysis of views file with viewsets and actions."""
        file_path = os.path.join(self.project_root, "myapp", "views.py")
        result = self.analyzer.analyze_file(file_path)
        
        # Check that all viewsets were detected
        self.assertIn("UserViewSet", result["classes"])
        self.assertIn("GroupViewSet", result["classes"])
        self.assertIn("CategoryViewSet", result["classes"])
        self.assertIn("ItemViewSet", result["classes"])
        
        # Check for action method
        item_viewset = result["classes"]["ItemViewSet"]
        self.assertIn("discount", item_viewset["functions"])
        
        # Verify the action decorator
        discount_func = item_viewset["functions"]["discount"]
        decorators = discount_func["decorators"]
        self.assertTrue(any("action" in decorator for decorator in decorators))
        
        # Check if it's correctly identified as an API
        self.assertTrue(discount_func["is_api"])
    
    def test_analyze_project(self):
        """Test full project analysis."""
        results_path = self.analyzer.analyze_project(self.project_root, self.output_dir)
        
        # Check that the results file exists
        self.assertTrue(os.path.exists(results_path))
        
        # Load the results
        results = self.analyzer.load_analysis_results(results_path)
        
        # Check that all files were analyzed
        self.assertIn(os.path.join(self.project_root, "myapp", "models.py"), results["result"])
        self.assertIn(os.path.join(self.project_root, "myapp", "views.py"), results["result"])
        self.assertIn(os.path.join(self.project_root, "myapp", "serializers.py"), results["result"])
        
        # Check for correct starting point detection
        self.assertEqual(self.analyzer.starting_point, os.path.join(self.project_root, "manage.py"))
        
        # Check for correct URL file detection
        self.assertEqual(self.analyzer.url_path, os.path.join(self.project_root, "test_project", "urls.py"))
    
    def test_resolve_dependencies(self):
        """Test dependency resolution between files."""
        # Analyze the project first
        self.analyzer.analyze_project(self.project_root, self.output_dir)
        
        # Check dependencies in views.py
        views_path = os.path.join(self.project_root, "myapp", "views.py")
        views_identifiers = self.analyzer.file_identifiers[views_path]
        
        # The views file should have imported the serializers
        self.assertIn("UserSerializer", views_identifiers["classes"])
        self.assertIn("GroupSerializer", views_identifiers["classes"])
        self.assertIn("CategorySerializer", views_identifiers["classes"])
        self.assertIn("ItemSerializer", views_identifiers["classes"])
        
        # The views file should also have imported the models
        self.assertIn("Category", views_identifiers["classes"])
        self.assertIn("Item", views_identifiers["classes"])
    
    def test_get_code_snippet(self):
        """Test code snippet extraction."""
        file_path = os.path.join(self.project_root, "myapp", "models.py")
        
        # Read the whole file for analysis
        with open(file_path, 'r') as f:
            file_content = f.read()
        
        # Verify the file content has what we're looking for
        assert "get_absolute_url" in file_content, "Test file doesn't contain expected method"
        
        # Extract the whole file content 
        snippet = self.analyzer.get_code_snippet(file_path, 1, 100)  # Use a large range to cover the file
        
        # Check for expected content
        self.assertIn("get_absolute_url", snippet)
        self.assertIn("class Item(models.Model):", snippet)
    
    def test_is_special_type_serializer(self):
        """Test detection of serializer classes."""
        # Analyze the project first
        self.analyzer.analyze_project(self.project_root, self.output_dir)
        
        serializers_path = os.path.join(self.project_root, "myapp", "serializers.py")
        
        # Test serializer detection
        self.assertTrue(self.analyzer.is_special_type(serializers_path, "UserSerializer", "serializer"))
        self.assertTrue(self.analyzer.is_special_type(serializers_path, "ItemSerializer", "serializer"))
        
        # Test non-serializer class
        models_path = os.path.join(self.project_root, "myapp", "models.py")
        self.assertFalse(self.analyzer.is_special_type(models_path, "Category", "serializer"))
    
    def test_is_special_type_viewset(self):
        """Test detection of viewset classes."""
        # Analyze the project first
        self.analyzer.analyze_project(self.project_root, self.output_dir)
        
        views_path = os.path.join(self.project_root, "myapp", "views.py")
        
        # Test viewset detection
        self.assertTrue(self.analyzer.is_special_type(views_path, "UserViewSet", "viewset"))
        self.assertTrue(self.analyzer.is_special_type(views_path, "ItemViewSet", "viewset"))
        
        # Test non-viewset class
        serializers_path = os.path.join(self.project_root, "myapp", "serializers.py")
        self.assertFalse(self.analyzer.is_special_type(serializers_path, "UserSerializer", "viewset"))
    
    def test_is_special_type_model(self):
        """Test detection of model classes."""
        # Analyze the project first
        self.analyzer.analyze_project(self.project_root, self.output_dir)
        
        models_path = os.path.join(self.project_root, "myapp", "models.py")
        
        # Test model detection
        self.assertTrue(self.analyzer.is_special_type(models_path, "Category", "model"))
        self.assertTrue(self.analyzer.is_special_type(models_path, "Item", "model"))
        
        # Test non-model class
        serializers_path = os.path.join(self.project_root, "myapp", "serializers.py")
        self.assertFalse(self.analyzer.is_special_type(serializers_path, "UserSerializer", "model"))
    
    def test_get_type_hierarchy(self):
        """Test getting the type hierarchy for a class."""
        # Analyze the project first
        self.analyzer.analyze_project(self.project_root, self.output_dir)
        
        serializers_path = os.path.join(self.project_root, "myapp", "serializers.py")
        
        # Get hierarchy for ItemSerializer
        hierarchy = self.analyzer.get_type_hierarchy(serializers_path, "ItemSerializer")
        
        # Verify the hierarchy contains ModelSerializer
        self.assertTrue(any("ModelSerializer" in entry["name"] for entry in hierarchy))
    
    def test_get_symbol_info(self):
        """Test retrieving information about a symbol."""
        # Analyze the project first
        self.analyzer.analyze_project(self.project_root, self.output_dir)
        
        views_path = os.path.join(self.project_root, "myapp", "views.py")
        
        # Get info about the ItemSerializer symbol from views context
        symbol_info = self.analyzer.get_symbol_info("ItemSerializer", views_path)
        
        # Verify the symbol was found and has correct info
        self.assertIsNotNone(symbol_info)
        self.assertEqual(symbol_info["name"], "ItemSerializer")
        
        # Path should point to serializers.py
        serializers_path = os.path.join(self.project_root, "myapp", "serializers.py")
        self.assertEqual(symbol_info["path"], serializers_path)
    
    @patch('python_analyzer.PythonCodeAnalyzer._resolve_import')
    def test_get_external_code(self, mock_resolve_import):
        """Test retrieving code for external symbols."""
        # Set up mock
        mock_analyzed = {
            "startLine": 5,
            "endLine": 10,
        }
        mock_resolve_import.return_value = (mock_analyzed, os.path.join(self.project_root, "external_lib", "utils.py"))
        
        # Set sys_path for test
        self.analyzer.sys_path = [self.project_root]
        
        # Create an unresolved import
        file_path = os.path.join(self.project_root, "myapp", "views.py")
        self.analyzer.unresolved_imports = {
            file_path: {
                "calculate_tax": {
                    "code": "from external_lib.utils import calculate_tax"
                }
            }
        }
        
        # Test getting external code
        result = self.analyzer.get_external_code("calculate_tax", file_path)
        
        # Verify the mock was called correctly
        mock_resolve_import.assert_called_with(
            self.analyzer.sys_path,
            "from external_lib.utils import calculate_tax",
            "calculate_tax",
            file_path
        )
        
        # Result should contain get_code_snippet return value
        self.assertIsNotNone(result)

if __name__ == '__main__':
    unittest.main()