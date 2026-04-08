import unittest
import os
import tempfile
import json
import sys
from unittest.mock import patch, MagicMock, mock_open
current_script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_script_dir)
common_path = os.path.join(project_root, 'common')

if common_path not in sys.path:
    sys.path.insert(0, common_path)
if project_root not in sys.path:
     sys.path.insert(0, project_root)

from common.core.framework_analyzer import FrameworkAnalyzer
from django_analyzer import DjangoAnalyzer
from common.core.code_analyzer import CodeAnalyzer
from python_analyzer import PythonCodeAnalyzer


class TestDjangoEndpointProcessing(unittest.TestCase):
    """
    Test the endpoint processing functionality of the DjangoAnalyzer class.
    """
    
    def setUp(self):
        """Set up test fixtures."""
        # Create mock code analyzer
        self.code_analyzer = MagicMock(spec=PythonCodeAnalyzer)
        
        # Sample project path
        self.project_path = "/tmp/test_project"
        
        # Create analyzer instance
        self.analyzer = DjangoAnalyzer(self.code_analyzer, self.project_path)
        
        # Set up sample analysis results
        self.setup_sample_analysis_results()
        
        # Set up sample endpoints
        self.setup_sample_endpoints()
        
        # Configure code_analyzer mock to return snippets
        self.code_analyzer.get_code_snippet.side_effect = self.mock_get_code_snippet
    
    def setup_sample_analysis_results(self):
        """Set up sample analysis results."""
        # Sample analysis results structure
        self.analysis_results = {
            "result": {
                # Document viewset file
                "/project/api/views.py": {
                    "classes": {
                        "DocumentViewSet": {
                            "startLine": 10,
                            "endLine": 50,
                            "properties": [
                                "serializer_class = DocumentSerializer",
                                "pagination_class = CustomPagination",
                                "filter_backends = [DjangoFilterBackend]",
                                "authentication_classes = [JWTAuthentication]"
                            ],
                            "parentClasses": {
                                "viewsets.ModelViewSet": {
                                    "name": "ModelViewSet",
                                    "path": "/lib/rest_framework/viewsets.py"
                                }
                            }
                        }
                    }
                },
                # Serializer file
                "/project/api/serializers.py": {
                    "classes": {
                        "DocumentSerializer": {
                            "startLine": 5,
                            "endLine": 30,
                            "properties": [
                                "created_by = CreatedByUserSerializer(read_only=True)",
                                "branch = DocumentBranchSerializer(write_only=True, required=False)"
                            ],
                            "innerClasses": [
                                {
                                    "name": "Meta",
                                    "properties": [
                                        "model = Document",
                                        "fields = ('id', 'name', 'doc_type')"
                                    ]
                                }
                            ],
                            "parentClasses": {
                                "serializers.ModelSerializer": {
                                    "name": "ModelSerializer",
                                    "path": "/lib/rest_framework/serializers.py"
                                }
                            }
                        }
                    }
                },
                # Model file
                "/project/api/models.py": {
                    "classes": {
                        "Document": {
                            "startLine": 8,
                            "endLine": 25,
                            "properties": [
                                "name = models.CharField(max_length=100)",
                                "doc_type = models.CharField(max_length=50)"
                            ],
                            "parentClasses": {
                                "models.Model": {
                                    "name": "Model",
                                    "path": "/lib/django/db/models/base.py"
                                }
                            }
                        }
                    }
                },
                # Authentication class
                "/project/api/auth.py": {
                    "classes": {
                        "JWTAuthentication": {
                            "startLine": 5,
                            "endLine": 20,
                            "properties": [],
                            "parentClasses": {
                                "BaseAuthentication": {
                                    "name": "BaseAuthentication",
                                    "path": "/lib/rest_framework/authentication.py"
                                }
                            }
                        }
                    }
                },
                # Pagination class
                "/project/api/pagination.py": {
                    "classes": {
                        "CustomPagination": {
                            "startLine": 3,
                            "endLine": 12,
                            "properties": ["page_size = 10"],
                            "parentClasses": {
                                "PageNumberPagination": {
                                    "name": "PageNumberPagination",
                                    "path": "/lib/rest_framework/pagination.py"
                                }
                            }
                        }
                    }
                }
            },
            "file_identifiers": {
                "/project/api/views.py": {
                    "classes": {
                        "DocumentSerializer": {
                            "name": "DocumentSerializer",
                            "path": "/project/api/serializers.py",
                            "type": "class"
                        },
                        "JWTAuthentication": {
                            "name": "JWTAuthentication",
                            "path": "/project/api/auth.py",
                            "type": "class"
                        },
                        "CustomPagination": {
                            "name": "CustomPagination",
                            "path": "/project/api/pagination.py",
                            "type": "class"
                        },
                        "DjangoFilterBackend": {
                            "name": "DjangoFilterBackend",
                            "path": "/lib/django_filters/rest_framework/backends.py",
                            "type": "class"
                        }
                    }
                },
                "/project/api/serializers.py": {
                    "classes": {
                        "Document": {
                            "name": "Document",
                            "path": "/project/api/models.py",
                            "type": "class"
                        }
                    }
                }
            }
        }
        
        # Set analysis results in analyzer
        self.analyzer.analysis_results = self.analysis_results
    
    def setup_sample_endpoints(self):
        """Set up sample endpoints."""
        self.sample_endpoints = [
            {
                "url": {"url": "/api/documents/", "parameter": []},
                "method": "get",
                "view": "DocumentViewSet",
                "path": "/project/api/views.py",
                "is_viewset": True,
                "function": "list"
            },
            {
                "url": {"url": "/api/documents/", "parameter": []},
                "method": "post",
                "view": "DocumentViewSet",
                "path": "/project/api/views.py",
                "is_viewset": True,
                "function": "create"
            },
            {
                "url": {"url": "/api/documents/{id}/", "parameter": [{"name": "id", "pattern": None, "type": None}]},
                "method": "get",
                "view": "DocumentViewSet",
                "path": "/project/api/views.py",
                "is_viewset": True,
                "function": "retrieve"
            }
        ]
        
        # Set endpoints in analyzer
        self.analyzer.endpoints = self.sample_endpoints
        
        # Set serializer and model mappings
        self.analyzer.is_serializer = {
            "/project/api/serializers.py:DocumentSerializer": True
        }
        self.analyzer.is_model = {
            "/project/api/models.py:Document": True
        }
    
    def mock_get_code_snippet(self, file_path, start_line, end_line):
        """Mock implementation of get_code_snippet."""
        # Return mock code based on file_path
        if "views.py" in file_path:
            return """
class DocumentViewSet(viewsets.ModelViewSet):
    queryset = Document.objects.all()
    serializer_class = DocumentSerializer
    pagination_class = CustomPagination
    filter_backends = [DjangoFilterBackend]
    authentication_classes = [JWTAuthentication]
    
    def get_queryset(self):
        return Document.objects.filter(user=self.request.user)
        
    @action(detail=True, methods=["post"], url_path="serial_state")
    def serial_state(self, request, **kwargs):
        main_doc = self.get_object()
        try:
            states = get_states(main_doc.id)
        except requests.exceptions.HTTPError as error:
            return Response({"success": False}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        else:
            return Response(states, status=status.HTTP_200_OK)
"""
        elif "serializers.py" in file_path:
            return """
class DocumentSerializer(serializers.ModelSerializer):
    created_by = CreatedByUserSerializer(read_only=True)
    branch = DocumentBranchSerializer(write_only=True, required=False)
    
    class Meta:
        model = Document
        fields = ('id', 'name', 'doc_type')
        read_only_fields = ('company', 'created_by')
"""
        elif "models.py" in file_path:
            return """
class Document(models.Model):
    name = models.CharField(max_length=100)
    doc_type = models.CharField(max_length=50)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE)
    
    def __str__(self):
        return self.name
"""
        elif "auth.py" in file_path:
            return """
class JWTAuthentication(BaseAuthentication):
    def authenticate(self, request):
        # Authentication logic
        pass
"""
        elif "pagination.py" in file_path:
            return """
class CustomPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
"""
        else:
            return "# Code not available"
    
    def test_get_endpoint_context(self):
        """Test the get_endpoint_context method."""
        # Get context for an endpoint
        endpoint = self.sample_endpoints[0]  # GET /api/documents/
        context = self.analyzer.get_endpoint_context(endpoint)
        
        # Verify context structure
        self.assertIsInstance(context, dict)
        self.assertIn("viewset_code", context)
        self.assertIn("serializer_code", context)
        self.assertIn("parent_code", context)
        self.assertIn("feature_code", context)
        
        # Verify viewset code content
        self.assertIn("DocumentViewSet", context["viewset_code"])
        self.assertIn("Source File:", context["viewset_code"])
        self.assertIn("Line Number:", context["viewset_code"])
        
        # Verify serializer code
        self.assertIn("DocumentSerializer", context["serializer_code"])
        
        # Verify feature code contains authentication, pagination, etc.
        self.assertIn("JWTAuthentication", context["feature_code"])
        self.assertIn("CustomPagination", context["feature_code"])
    
    def test_get_serializer_code(self):
        """Test the _get_serializer_code method."""
        # Get viewset code
        viewset_code = self.mock_get_code_snippet("/project/api/views.py", 10, 50)
        
        # Get serializer code
        serializer_code = self.analyzer._get_serializer_code(viewset_code, "/project/api/views.py", True)
        
        # Verify serializer code content
        self.assertIn("===###===", serializer_code)
        self.assertIn("DocumentSerializer", serializer_code)
        self.assertIn("Source File:", serializer_code)
        self.assertIn("Line Number:", serializer_code)
        
        # Verify model code is included
        self.assertIn("Document", serializer_code)
        self.assertIn("models.Model", serializer_code)
    
    # def test_get_feature_code(self):
    #     """Test the _get_feature_code method."""
    #     # Get viewset code
    #     viewset_code = self.mock_get_code_snippet("/project/api/views.py", 10, 50)
        
    #     # Get feature code
    #     feature_code = self.analyzer._get_feature_code(viewset_code, "/project/api/views.py", set())
        
    #     # Verify feature code content
    #     self.assertIn("===###===", feature_code)
    #     self.assertIn("JWTAuthentication", feature_code)
    #     self.assertIn("CustomPagination", feature_code)
        
    #     # Verify sources are included
    #     self.assertIn("Source File:", feature_code)
    #     self.assertIn("Line Number:", feature_code)
    
    def test_extract_class_attribute(self):
        """Test the _extract_class_attribute method."""
        # Test code with class attributes
        code = """
class TestClass:
    single_value = SingleClass
    list_values = [Class1, Class2, Class3]
    attribute_value = module.AttributeClass
        """
        
        # Extract single value attribute
        single_values = self.analyzer._extract_class_attribute(code, "single_value")
        self.assertEqual(len(single_values), 1)
        self.assertEqual(single_values[0], "SingleClass")
        
        # Extract list attribute
        list_values = self.analyzer._extract_class_attribute(code, "list_values")
        self.assertEqual(len(list_values), 3)
        self.assertIn("Class1", list_values)
        self.assertIn("Class2", list_values)
        self.assertIn("Class3", list_values)
        
        # Extract attribute with module
        attr_values = self.analyzer._extract_class_attribute(code, "attribute_value")
        self.assertEqual(len(attr_values), 1)
        self.assertEqual(attr_values[0], "module.AttributeClass")
    
    # @patch('json.loads')
    # def test_identify_required_symbols(self, mock_json_loads):
    #     """Test the identify_required_symbols method."""
    #     # Mock LLM response (in real implementation, this would be parsed)
    #     mock_json_loads.return_value = {
    #         "missing_functions": {
    #             "get_states": {"filepath": "/project/api/utils.py"}
    #         },
    #         "missing_classes": {
    #             "CustomPermission": {"filepath": "/project/api/permissions.py"}
    #         },
    #         "missing_variables": {
    #             "PERMISSION_TYPES": {"filepath": "/project/api/constants.py"}
    #         }
    #     }
        
    #     # Get endpoint and context
    #     endpoint = self.sample_endpoints[2]  # GET /api/documents/{id}/
    #     context = {"viewset_code": "test code"}
        
    #     # Call identify_required_symbols
    #     required_symbols = self.analyzer.identify_required_symbols(endpoint, context)
        
    #     # In a real test with LLM integration, we would verify the parsed output
    #     # For this unit test, we're testing that our placeholder implementation returns something
    #     self.assertIsInstance(required_symbols, list)
    #     self.assertTrue(len(required_symbols) > 0)
        
    #     # Each symbol should have type, name and path
    #     for symbol in required_symbols:
    #         self.assertIn("type", symbol)
    #         self.assertIn("name", symbol)
    #         self.assertIn("path", symbol)
    
    # def test_get_required_functions_prompt(self):
    #     """Test the _get_required_functions_prompt method."""
    #     # Create test data
    #     url = "/api/documents/{id}/"
    #     method = "get"
    #     function_name = "retrieve"
    #     context = {
    #         "viewset_code": "class DocumentViewSet(viewsets.ModelViewSet):\n    pass",
    #         "serializer_code": "class DocumentSerializer(serializers.ModelSerializer):\n    pass"
    #     }
        
    #     # Get prompt
    #     prompt = self.analyzer._get_required_functions_prompt(url, method, function_name, context)
        
    #     # Verify prompt content
    #     self.assertIn(url, prompt)
    #     self.assertIn(method, prompt)
    #     self.assertIn(function_name, prompt)
    #     self.assertIn("DocumentViewSet", prompt)
    #     self.assertIn("DocumentSerializer", prompt)
        
    #     # Verify prompt structure for LLM
    #     self.assertIn("missing_functions", prompt)
    #     self.assertIn("missing_classes", prompt)
    #     self.assertIn("missing_variables", prompt)
    #     self.assertIn("json", prompt.lower())
    
    # def test_get_missing_context_with_functions(self):
    #     """Test get_missing_context with functions."""
    #     # Create test data
    #     endpoint_context = {
    #         "viewset_code": "class DocumentViewSet(viewsets.ModelViewSet):\n    pass"
    #     }
        
    #     # Setup mock for code_analyzer.get_code_snippet
    #     self.code_analyzer.get_code_snippet.return_value = "def get_states(doc_id):\n    return {'state': 'test'}"
        
    #     # Create required symbols
    #     required_symbols = [
    #         {
    #             "type": "function",
    #             "name": "get_states",
    #             "path": "/project/api/utils.py",
    #             "reason": "Used in endpoint"
    #         }
    #     ]
        
    #     # Setup mock for file existence checks
    #     with patch('os.path.exists', return_value=True):
    #         # Mock result lookup
    #         self.analysis_results["result"]["/project/api/utils.py"] = {
    #             "functions": {
    #                 "get_states": {
    #                     "startLine": 5,
    #                     "endLine": 10
    #                 }
    #             }
    #         }
            
    #         # Call get_missing_context
    #         updated_context = self.analyzer.get_missing_context(endpoint_context, required_symbols)
            
    #         # Verify function code was added
    #         self.assertIn("missing_functions_code", updated_context)
    #         self.assertIn("get_states", updated_context["missing_functions_code"])
            
    #         # Verify code structure
    #         self.assertIn("Source File:", updated_context["missing_functions_code"])
    #         self.assertIn("Line Number:", updated_context["missing_functions_code"])
    #         self.assertIn("Code Snippet:", updated_context["missing_functions_code"])

    # def test_get_authentication_mechanisms(self):
    #     """Test get_authentication_mechanisms method."""
    #     # Setup default settings
    #     self.analyzer.default_settings = {
    #         "DEFAULT_AUTHENTICATION_CLASSES": [
    #             "rest_framework.authentication.TokenAuthentication",
    #             "rest_framework.authentication.SessionAuthentication"
    #         ]
    #     }
        
    #     # Call get_authentication_mechanisms
    #     auth_mechanisms = self.analyzer.get_authentication_mechanisms()
        
    #     # Verify authentication mechanisms
    #     self.assertIsInstance(auth_mechanisms, list)
        
    #     # Should include default authentications
    #     default_auth_found = False
    #     for auth in auth_mechanisms:
    #         if auth["name"] == "rest_framework.authentication.TokenAuthentication" and auth["source"] == "settings":
    #             default_auth_found = True
    #             break
    #     self.assertTrue(default_auth_found, "Default authentication not found")
        
    #     # Should include viewset authentication
    #     viewset_auth_found = False
    #     for auth in auth_mechanisms:
    #         if "JWTAuthentication" in auth["name"] and "views.py" in auth["source"]:
    #             viewset_auth_found = True
    #             break
    #     self.assertTrue(viewset_auth_found, "Viewset authentication not found")


class TestDjangoEndpointProcessingIntegration(unittest.TestCase):
    """Integration tests for DjangoAnalyzer with real files."""
    
    @classmethod
    def setUpClass(cls):
        """Set up test fixtures for the class."""
        # Create temporary directory for test project
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.project_path = cls.temp_dir.name
        
        # Create simple Django project structure
        cls.create_test_project_structure(cls.project_path)
        
        # Create actual code analyzer
        cls.code_analyzer = PythonCodeAnalyzer()
        
        # Create analyzer instance
        cls.analyzer = DjangoAnalyzer(cls.code_analyzer, cls.project_path)
        
        # Analyze project
        cls.analysis_path = cls.analyzer.analyze_project(cls.project_path)
    
    @classmethod
    def tearDownClass(cls):
        """Clean up test fixtures."""
        cls.temp_dir.cleanup()
    
    @classmethod
    def create_test_project_structure(cls, project_path):
        """Create a simple Django project structure for testing."""
        # Create directories
        os.makedirs(os.path.join(project_path, "project"), exist_ok=True)
        os.makedirs(os.path.join(project_path, "project", "api"), exist_ok=True)
        
        # Create manage.py
        with open(os.path.join(project_path, "manage.py"), "w") as f:
            f.write("""#!/usr/bin/env python
import os
import sys

if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "project.settings")
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)
""")
        
        # Create settings.py
        with open(os.path.join(project_path, "project", "settings.py"), "w") as f:
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
    'rest_framework',
    'project.api',
]

ROOT_URLCONF = 'project.urls'

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.TokenAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 10,
}
""")
        
        # Create urls.py
        with open(os.path.join(project_path, "project", "urls.py"), "w") as f:
            f.write("""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from project.api.views import DocumentViewSet

router = DefaultRouter()
router.register(r'documents', DocumentViewSet, basename='document')

urlpatterns = [
    path('api/', include(router.urls)),
]
""")
        
        # Create models.py
        with open(os.path.join(project_path, "project", "api", "models.py"), "w") as f:
            f.write("""
from django.db import models
from django.contrib.auth.models import User

class Document(models.Model):
    name = models.CharField(max_length=100)
    content = models.TextField()
    created_by = models.ForeignKey(User, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return self.name
""")
        
        # Create serializers.py
        with open(os.path.join(project_path, "project", "api", "serializers.py"), "w") as f:
            f.write("""
from rest_framework import serializers
from project.api.models import Document

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'username', 'email')

class DocumentSerializer(serializers.ModelSerializer):
    created_by = UserSerializer(read_only=True)
    
    class Meta:
        model = Document
        fields = ('id', 'name', 'content', 'created_by', 'created_at')
        read_only_fields = ('created_at',)
""")
        
        # Create views.py
        with open(os.path.join(project_path, "project", "api", "views.py"), "w") as f:
            f.write("""
from rest_framework import viewsets, permissions
from project.api.models import Document
from project.api.serializers import DocumentSerializer
from project.api.utils import get_document_stats

class DocumentViewSet(viewsets.ModelViewSet):
    queryset = Document.objects.all()
    serializer_class = DocumentSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        return Document.objects.filter(created_by=self.request.user)
    
    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)
    
    @action(detail=True, methods=['get'])
    def stats(self, request, pk=None):
        document = self.get_object()
        stats = get_document_stats(document)
        return Response(stats)
""")
        
        # Create utils.py
        with open(os.path.join(project_path, "project", "api", "utils.py"), "w") as f:
            f.write("""
def get_document_stats(document):
    return {
        'word_count': len(document.content.split()),
        'char_count': len(document.content)
    }
""")
    
    def test_integration_get_endpoints(self):
        """Integration test for get_endpoints."""
        # Get endpoints
        endpoints = self.analyzer.get_endpoints()
        
        # Verify endpoints
        self.assertIsInstance(endpoints, list)
        self.assertTrue(len(endpoints) > 0)
        
        # Check for typical viewset endpoints
        methods = set()
        for endpoint in endpoints:
            methods.add(endpoint.get("method"))
            self.assertEqual(endpoint.get("view"), "DocumentViewSet")
        
        # Verify we have standard HTTP methods
        self.assertTrue("get" in methods)
        self.assertTrue("post" in methods)
    
    def test_integration_get_endpoint_context(self):
        """Integration test for get_endpoint_context."""
        # Get endpoints
        endpoints = self.analyzer.get_endpoints()
        
        # Choose a GET endpoint
        get_endpoint = None
        for endpoint in endpoints:
            if endpoint.get("method") == "get" and "stats" not in endpoint.get("url", {}).get("url", ""):
                get_endpoint = endpoint
                break
        
        self.assertIsNotNone(get_endpoint, "No GET endpoint found")
        
        # Get context
        context = self.analyzer.get_endpoint_context(get_endpoint)
        
        # Verify context
        self.assertIsInstance(context, dict)
        self.assertIn("viewset_code", context)
        self.assertIn("serializer_code", context)
        
        # Verify the viewset code is included
        self.assertIn("DocumentViewSet", context["viewset_code"])
        
        # Verify the serializer code is included
        self.assertIn("DocumentSerializer", context["serializer_code"])
    
    # def test_integration_identify_required_symbols(self):
    #     """Integration test for identify_required_symbols."""
    #     # Get endpoints
    #     endpoints = self.analyzer.get_endpoints()
        
    #     # Find an endpoint with the stats action
    #     stats_endpoint = None
    #     for endpoint in endpoints:
    #         if "stats" in endpoint.get("url", {}).get("url", ""):
    #             stats_endpoint = endpoint
    #             break
        
    #     self.assertIsNotNone(stats_endpoint, "No stats endpoint found")
        
    #     # Get context
    #     context = self.analyzer.get_endpoint_context(stats_endpoint)
        
    #     # Normally we'd test with the LLM call, but we'll mock for this test
    #     with patch.object(self.analyzer, '_get_required_functions_prompt', return_value=""):
    #         # In a real scenario, the LLM would identify get_document_stats as required
    #         required_symbols = [
    #             {
    #                 "type": "function",
    #                 "name": "get_document_stats",
    #                 "path": os.path.join(self.project_path, "project", "api", "utils.py"),
    #                 "reason": "Used in stats endpoint"
    #             }
    #         ]
            
    #         # Get missing context
    #         updated_context = self.analyzer.get_missing_context(context, required_symbols)
            
    #         # Verify missing functions code
    #         self.assertIn("missing_functions_code", updated_context)
    #         self.assertIn("get_document_stats", updated_context["missing_functions_code"])
    #         self.assertIn("word_count", updated_context["missing_functions_code"])


if __name__ == '__main__':
    unittest.main()