// FILE: genapidocs_v2/java_analyzer_impl/src/main/java/com/analyzer/ListClasses.java

package com.analyzer;

import com.analyzer.EndPointRecog.*;
import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonParser;

import org.apache.commons.lang3.tuple.Triple;
import org.json.simple.JSONArray;
import org.json.simple.JSONObject;
import org.json.simple.parser.JSONParser;
import org.json.simple.parser.ParseException;
import soot.G;
import soot.PackManager;
import soot.Scene;
import soot.SootClass;
import soot.options.Options;

import java.io.File;
import java.io.FileReader;
import java.io.FileWriter;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.*;
import java.util.regex.Pattern;
import java.util.stream.Stream;
import org.apache.commons.lang3.tuple.Pair;
import org.apache.commons.lang3.tuple.Triple;

public class ListClasses {

    private static class ClassInfo {
        long startLine;
        long endLine;
        String classFileName;

        ClassInfo(long startLine, long endLine, String classFileName) {
            this.startLine = startLine;
            this.endLine = endLine;
            this.classFileName = classFileName;
        }
    }

    private static void dumpJSONToFile(JSONObject obj, String outputDir, String baseFileName) {
        try {
            Path dirPath = Paths.get(outputDir);
            Files.createDirectories(dirPath);
        } catch (IOException e) {
            System.err.println("Error creating output directory: " + outputDir + " - " + e.getMessage());
            return;
        }

        String fullPath = Paths.get(outputDir, baseFileName).toString();
        try (FileWriter file = new FileWriter(fullPath)) {
            Gson gson = new GsonBuilder().setPrettyPrinting().create();
            String prettyJson = gson.toJson(JsonParser.parseString(obj.toJSONString()));
            file.write(prettyJson);
            file.flush();
            System.out.println("Successfully wrote JSON to " + fullPath);
        } catch (IOException e) {
            System.err.println("Error writing to JSON file: " + fullPath + " - " + e.getMessage());
            e.printStackTrace();
        }
    }

    public static void main(String[] args) {
        System.out.println("--- JAVA ANALYZER MAIN METHOD STARTED ---");
        if (args.length < 4) { // <-- MODIFIED: Expect 4 arguments now
            System.err.println("FATAL ERROR: Insufficient arguments provided.");
            System.err.println("Expected: <path_for_soot> <project_source_root> <output_dir> <framework>"); // <-- MODIFIED
            System.err.println("Received " + args.length + " arguments: " + Arrays.toString(args));
            System.exit(1);
        }
        String multiPathForSoot = args[0];
        String projectSourceDir = args[1];
        String outputDir = args[2];
        String frameworkName = args[3];

        System.out.println("  Received Arg 0 (Multi-path for Soot): " + multiPathForSoot);
        System.out.println("  Received Arg 1 (Project Source Root): " + projectSourceDir);
        System.out.println("  Received Arg 2 (Output Directory): " + outputDir);
        System.out.println("  Received Arg 3 (Framework): " + frameworkName);
        System.out.println("-----------------------------------------");

        String respectorBaseFile = "soot-respector.json";
        String identifierBaseFile = "soot-identifiers.json";
        String lineNumberBaseFile = "soot-line-numbers.json";
        String finalAnalysisBaseFile = "soot-analysis.json";

        G.reset();
        Options.v().set_output_format(Options.output_format_none);
        Options.v().set_allow_phantom_refs(true);
        Options.v().set_prepend_classpath(true);
        Options.v().set_keep_line_number(true);
        Options.v().setPhaseOption("jb", "use-original-names:true");
        Options.v().set_no_bodies_for_excluded(true);
        Options.v().set_whole_program(true);

        Options.v().set_soot_classpath(multiPathForSoot
                                    + File.pathSeparator
                                    + System.getProperty("java.class.path"));

        // Use the multi-path string for Soot's process_dir as well
        Options.v().set_process_dir(Arrays.asList(multiPathForSoot.split(Pattern.quote(File.pathSeparator))));

        List<String> classesToProcess = new ArrayList<>();
        String[] sootIndividualPaths = multiPathForSoot.split(Pattern.quote(File.pathSeparator));

        System.out.println("Processing " + sootIndividualPaths.length + " individual paths from Soot process_dir argument.");
        for (String singlePath : sootIndividualPaths) {
            Path moduleClassesPath = Paths.get(singlePath);
            if (!Files.isDirectory(moduleClassesPath)) {
                System.out.println("WARNING: Path component is not a directory, skipping: " + singlePath);
                continue;
            }

            try (Stream<Path> walk = Files.walk(moduleClassesPath)) {
                walk.filter(p -> p.toString().endsWith(".class")).forEach(p -> {
                    String pathString = p.toString();
                    String classesDir = moduleClassesPath.toString() + File.separator;
                    String relativePath = pathString.substring(classesDir.length());
                    String className = relativePath.replace(File.separator, ".").replace(".class", "");
                    classesToProcess.add(className);
                });
            } catch (IOException e) {
                System.err.println("FATAL: I/O error while walking path: " + singlePath);
                e.printStackTrace();
                System.exit(1);
            }
        }

        if (classesToProcess.isEmpty()) {
            System.err.println("FATAL: No .class files found in any of the provided paths: " + multiPathForSoot);
            System.exit(1);
        }

        Scene.v().loadNecessaryClasses();
        System.out.println("Loading " + classesToProcess.size() + " discovered classes into Soot Scene...");
        for (String className : classesToProcess) {
            SootClass sc = Scene.v().loadClassAndSupport(className);
            sc.setApplicationClass();
        }
        System.out.println("Finished loading classes into Scene.");

        PackManager.v().runPacks();
        PreprocessFramework processedFramework = PreprocessFramework.getEndPointInfo(Scene.v(), frameworkName);

        JSONObject respectorDump = new JSONObject();
        JSONArray methodsArray = new JSONArray();
        for (EndPointMethodInfo methodInfo : processedFramework.endPointMethodData) {
            if (methodInfo.isEndpointMethod) {
                methodsArray.add(methodInfo.toJSON());
            }
        }
        respectorDump.put("endpointMethods", methodsArray);
        dumpJSONToFile(respectorDump, outputDir, respectorBaseFile);

        JSONObject identifiersDump = new JSONObject();
        JSONArray classIdentifiersArray = new JSONArray();
        for (ClassIdentifersInfo classInfo : processedFramework.classesIdentifersInfo) {
            classIdentifiersArray.add(classInfo.toJSON());
        }
        identifiersDump.put("classIdentifiers", classIdentifiersArray);
        dumpJSONToFile(identifiersDump, outputDir, identifierBaseFile);

        GetLineNumbers getLineNumbers = new GetLineNumbers();
        try {
            ArrayList<ClassLineNumbers> output = getLineNumbers.processJavaFiles(projectSourceDir);
            JSONObject classLineNumbersDump = new JSONObject();
            JSONArray classLineNumbersJsonArray = new JSONArray();
            for (ClassLineNumbers classLineNumbers : output) {
                classLineNumbersJsonArray.add(classLineNumbers.toJSON());
            }
            classLineNumbersDump.put("classLineNumbers", classLineNumbersJsonArray);
            dumpJSONToFile(classLineNumbersDump, outputDir, lineNumberBaseFile);
        } catch (Exception e) {
            System.err.println("Error processing project for line numbers: " + projectSourceDir);
            e.printStackTrace();
        }

        String lineNumbersFileFullPath = Paths.get(outputDir, lineNumberBaseFile).toString();
        String identifierFileFullPath = Paths.get(outputDir, identifierBaseFile).toString();
        String finalAnalysisFileFullPath = Paths.get(outputDir, finalAnalysisBaseFile).toString();
        try {
            if (new File(lineNumbersFileFullPath).exists() && new File(identifierFileFullPath).exists()) {
                mergeJsonFiles(lineNumbersFileFullPath, identifierFileFullPath, finalAnalysisFileFullPath);
            } else {
                System.err.println("Error: Cannot merge files. Input file(s) missing.");
            }
        } catch (Exception e) {
            System.err.println("Error merging JSON files: " + e.getMessage());
            e.printStackTrace();
        }

        System.out.println("Java analysis phase complete.");
    }

   public static void mergeJsonFiles(String lineNumbersFileFullPath, String classIdentifiersFileFullPath, String outputFileFullPath)
            throws IOException, ParseException {

        JSONParser parser = new JSONParser();
        JSONObject lineNumbersJson = (JSONObject) parser.parse(new FileReader(lineNumbersFileFullPath));
        JSONObject classIdentifiersJson = (JSONObject) parser.parse(new FileReader(classIdentifiersFileFullPath));

        Map<String, String> sootFqnToOriginalFqnMap = new HashMap<>();
        Map<String, Map<String, List<MethodLineInfo>>> lineInfoMap = new HashMap<>();

        class ClassInfoForMerge {
            long startLine;
            long endLine;
            String classFileName;

            ClassInfoForMerge(long startLine, long endLine, String classFileName) {
                this.startLine = startLine;
                this.endLine = endLine;
                this.classFileName = classFileName;
            }
        }
        Map<String, ClassInfoForMerge> classInfoMap = new HashMap<>();

        JSONArray classLineNumbersArray = (JSONArray) lineNumbersJson.get("classLineNumbers");
        if (classLineNumbersArray != null) {
            for (Object obj : classLineNumbersArray) {
                JSONObject classNode = (JSONObject) obj;
                String originalClassName = (String) classNode.get("className");
                String sootCompatibleFqn = (String) classNode.get("sootCompatibleFqn");

                if (sootCompatibleFqn != null && !sootCompatibleFqn.equals(originalClassName)) {
                    sootFqnToOriginalFqnMap.put(sootCompatibleFqn, originalClassName);
                }

                classInfoMap.put(originalClassName, new ClassInfoForMerge(
                    (long) classNode.get("startLine"),
                    (long) classNode.get("endLine"),
                    (String) classNode.get("classFileName")
                ));

                Map<String, List<MethodLineInfo>> methodMap = new HashMap<>();
                lineInfoMap.put(originalClassName, methodMap);
                JSONArray methodsArray = (JSONArray) classNode.get("methods");
                if (methodsArray != null) {
                    for (Object methodObj : methodsArray) {
                        JSONObject methodNode = (JSONObject) methodObj;
                        String methodName = (String) methodNode.get("methodName");
                        long start = (long) methodNode.get("startLine");
                        long end = (long) methodNode.get("endLine");
                        long paramCount = (long) methodNode.get("parameterCount");
                        methodMap.computeIfAbsent(methodName, k -> new ArrayList<>()).add(new MethodLineInfo((int)start, (int)end, methodName, (int)paramCount));
                    }
                }
            }
        }

        JSONArray classIdentifiersArray = (JSONArray) classIdentifiersJson.get("classIdentifiers");
        if (classIdentifiersArray != null) {
            for (Object obj : classIdentifiersArray) {
                JSONObject classIdNode = (JSONObject) obj;
                String classNameFromSoot = (String) classIdNode.get("className");

                String keyForLookup = classNameFromSoot;
                if (!classInfoMap.containsKey(keyForLookup)) {
                    String fallbackKey = sootFqnToOriginalFqnMap.get(classNameFromSoot);
                    if (fallbackKey != null) {
                        keyForLookup = fallbackKey;
                    }
                }

                if (classInfoMap.containsKey(keyForLookup)) {
                    ClassInfoForMerge info = classInfoMap.get(keyForLookup);
                    classIdNode.put("startLine", info.startLine);
                    classIdNode.put("endLine", info.endLine);
                    classIdNode.put("classFileName", info.classFileName);
                }

                Map<String, List<MethodLineInfo>> classLineInfos = lineInfoMap.get(keyForLookup);
                if (classLineInfos == null) continue;

                JSONArray functionsArray = (JSONArray) classIdNode.get("functions");
                if (functionsArray != null) {
                    for (Object funcObj : functionsArray) {
                        JSONObject functionNode = (JSONObject) funcObj;
                        String methodName = (String) functionNode.get("methodName");
                        JSONArray paramsArray = (JSONArray) functionNode.get("parameters");
                        int sootParamCount = (paramsArray == null) ? 0 : paramsArray.size();
                        List<MethodLineInfo> overloads = classLineInfos.get(methodName);
                        if (overloads != null && !overloads.isEmpty()) {
                            MethodLineInfo bestMatch = null;
                            for (MethodLineInfo lineInfo : overloads) {
                                if (lineInfo.parameterCount == sootParamCount) {
                                    bestMatch = lineInfo;
                                    break;
                                }
                            }
                            if (bestMatch != null) {
                                functionNode.put("startLine", bestMatch.startLine);
                                functionNode.put("endLine", bestMatch.endLine);
                                overloads.remove(bestMatch);
                            }
                        }
                    }
                }
            }
        }

        Gson gson = new GsonBuilder().setPrettyPrinting().create();
        String prettyJson = gson.toJson(JsonParser.parseString(classIdentifiersJson.toJSONString()));

        try (FileWriter writer = new FileWriter(outputFileFullPath)) {
             writer.write(prettyJson);
             System.out.println("Successfully wrote merged JSON to: " + outputFileFullPath);
        } catch (IOException e) {
              System.err.println("Error writing merged JSON file: " + outputFileFullPath + " - " + e.getMessage());
              throw e;
        }
    }
}