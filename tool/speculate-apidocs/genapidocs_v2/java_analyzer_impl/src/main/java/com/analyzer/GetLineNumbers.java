package com.analyzer;

import com.github.javaparser.JavaParser;
import com.github.javaparser.ParseResult;
import com.github.javaparser.Position;
import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.ast.Node;
import com.github.javaparser.ast.body.ClassOrInterfaceDeclaration;
import com.github.javaparser.ast.body.MethodDeclaration;
import com.github.javaparser.ast.body.TypeDeclaration;
import com.github.javaparser.ast.PackageDeclaration;
import org.json.simple.JSONObject;

import java.io.File;
import java.io.FileNotFoundException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.stream.Collectors;
import java.util.stream.Stream;

public class GetLineNumbers {
    public ArrayList<ClassLineNumbers> processJavaFiles(String projectSourceRoot) throws Exception {
        List<Path> javaFiles = findJavaFiles(projectSourceRoot);
        ArrayList<ClassLineNumbers> classLineNumbersList = new ArrayList<>();
        for (Path javaFile : javaFiles) {
            ArrayList<ClassLineNumbers> toAdd = processJavaFile(javaFile);
            if (toAdd != null) {
                classLineNumbersList.addAll(toAdd);
            }
        }
        return classLineNumbersList;
    }

    private List<Path> findJavaFiles(String projectPath) throws Exception {
        try (Stream<Path> paths = Files.walk(Paths.get(projectPath))) {
            return paths.filter(Files::isRegularFile).filter(path -> path.toString().endsWith(".java")).collect(Collectors.toList());
        }
    }

    private ArrayList<ClassLineNumbers> processJavaFile(Path javaFile) {
        try {
            JavaParser parser = new JavaParser();
            ParseResult<CompilationUnit> parseResult = parser.parse(javaFile.toFile());

            if (!parseResult.isSuccessful() || !parseResult.getResult().isPresent()) {
                System.err.println("Failed to parse " + javaFile + ": " + parseResult.getProblems());
                return null;
            }

            CompilationUnit cu = parseResult.getResult().get();
            ArrayList<ClassLineNumbers> classes = new ArrayList<>();
            String packageName = cu.getPackageDeclaration().map(PackageDeclaration::getNameAsString).orElse("");

            cu.findAll(ClassOrInterfaceDeclaration.class).forEach(classDecl -> {
                String simpleName = classDecl.getNameAsString();
                String originalClassName = packageName.isEmpty() ? simpleName : packageName + "." + simpleName;
                String sootFqn = getSootCompatibleFqn(classDecl);
                extractDeclarationInfo(classDecl, originalClassName, sootFqn, javaFile.toString(), classes);
            });

            cu.findAll(com.github.javaparser.ast.body.EnumDeclaration.class).forEach(enumDecl -> {
                String simpleName = enumDecl.getNameAsString();
                String originalClassName = packageName.isEmpty() ? simpleName : packageName + "." + simpleName;
                String sootFqn = getSootCompatibleFqn(enumDecl);
                extractDeclarationInfo(enumDecl, originalClassName, sootFqn, javaFile.toString(), classes);
            });

            return classes;
        } catch (Exception e) {
            System.err.println("Error processing file " + javaFile + ": " + e.getMessage());
            e.printStackTrace();
        }
        return null;
    }

    private void extractDeclarationInfo(TypeDeclaration<?> typeDecl, String originalFqn, String sootFqn, String filePath, ArrayList<ClassLineNumbers> classList) {
        // ... (body of this method is unchanged) ...
        ArrayList<MethodLineInfo> methods = new ArrayList<>();
        Optional<Position> beginPosition = typeDecl.getBegin();
        Optional<Position> endPosition = typeDecl.getEnd();
        if (beginPosition.isPresent() && endPosition.isPresent()) {
            int startLine = beginPosition.get().line;
            int endLine = endPosition.get().line;
            typeDecl.findAll(MethodDeclaration.class).forEach(methodDecl -> {
                String methodName = methodDecl.getNameAsString();
                int paramCount = methodDecl.getParameters().size();
                Optional<Position> methodBegin = methodDecl.getBegin();
                Optional<Position> methodEnd = methodDecl.getEnd();
                if (methodBegin.isPresent() && methodEnd.isPresent()) {
                    int methodStartLine = methodBegin.get().line;
                    int methodEndLine = methodEnd.get().line;
                    methods.add(new MethodLineInfo(methodStartLine, methodEndLine, methodName, paramCount));
                }
            });
            classList.add(new ClassLineNumbers(methods, originalFqn, startLine, endLine, filePath, sootFqn));
        }
    }

    // This robust helper method correctly generates the FQN for Soot.
    private String getSootCompatibleFqn(TypeDeclaration<?> typeDecl) {
        StringBuilder nameBuilder = new StringBuilder(typeDecl.getNameAsString());
        Optional<Node> parentNodeOpt = typeDecl.getParentNode();
        while (parentNodeOpt.isPresent() && parentNodeOpt.get() instanceof TypeDeclaration) {
            TypeDeclaration<?> parentType = (TypeDeclaration<?>) parentNodeOpt.get();
            nameBuilder.insert(0, "$");
            nameBuilder.insert(0, parentType.getNameAsString());
            parentNodeOpt = parentType.getParentNode();
        }
        typeDecl.findCompilationUnit().flatMap(CompilationUnit::getPackageDeclaration).ifPresent(pkg -> {
            nameBuilder.insert(0, ".");
            nameBuilder.insert(0, pkg.getNameAsString());
        });
        return nameBuilder.toString();
    }
}