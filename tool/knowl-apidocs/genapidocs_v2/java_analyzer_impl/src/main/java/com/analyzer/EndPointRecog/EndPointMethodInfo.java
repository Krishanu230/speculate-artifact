package com.analyzer.EndPointRecog;

import fj.P;
import org.json.simple.JSONArray;
import org.json.simple.JSONObject;
import soot.RefType;
import soot.SootMethod;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Optional;
import java.util.TreeSet;
import java.util.stream.Collectors;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import org.apache.commons.lang3.tuple.Pair;
import org.apache.commons.lang3.tuple.Triple;
import com.analyzer.EndPointRecog.ParameterAnnotation.paramLoction;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import org.json.simple.JSONObject;
import org.json.simple.JSONArray;
import org.apache.commons.lang3.tuple.Pair;

public class EndPointMethodInfo {
  public transient SootMethod method;
  public String name;
  public String className ; 
  public ArrayList<String> requestMethod;
  public ArrayList<EndPointParamInfo> parameterInfo;
  public ArrayList<String> methodMappingPath;
  public ArrayList<String> classMappingPath;
  public ArrayList<EndPointParamInfo> fieldParameterInfo;
  public HashMap<EndPointParamInfo, String> fieldParameterRegex;
  final public int responseStatus;
  public transient final boolean hasPathExplosion;
  public transient ArrayList<EndPointMethodInfo> parentResourceMethod=new ArrayList<>();
  public transient ArrayList<ArrayList<String>> methodHierarchies  ;

  public final String methodSignature;
  public final ArrayList<String> consumes;
  public final ArrayList<String> produces;
  public final ArrayList<EndPointParamInfo> allParameters;

  public MethodIdentifiersInfo methodIdentifiersInfo;

  public transient ArrayList<Pair<String, ArrayList<EndPointParamInfo>>> allPaths;
  protected transient ArrayList<Triple<String, ArrayList<EndPointParamInfo>, String>> allPathPathParamOpTriple;

  public boolean isEndpointMethod = true ; 

  protected static final Pattern pathParamPattern = Pattern.compile("\\{(\\w+)\\}");
  protected static final Pattern pathParamPatternWithRegex = Pattern.compile("\\{(\\w+:.+)\\}");

  private static Logger logger = LoggerFactory.getLogger(EndPointMethodInfo.class);

  public EndPointMethodInfo(SootMethod method,
                            String name,
                            String className,
                            ArrayList<String> requestMethod,
                            ArrayList<EndPointParamInfo> parameterInfo,
                            ArrayList<String> methodMappingPath,
                            ArrayList<String> classMappingPath,
                            ArrayList<EndPointParamInfo> fieldParameterInfo,
                            int responseStatus,
                            boolean hasPathExplosion,
                            String methodSignature,
                            ArrayList<String> consumes,
                            ArrayList<String> produces,
                            ArrayList<EndPointParamInfo> allParameters) {
      this.method = method;
      this.name = name;
      this.className = className;
      this.requestMethod = requestMethod;
      this.parameterInfo = parameterInfo;
      this.methodMappingPath = methodMappingPath;
      this.classMappingPath = classMappingPath;
      this.fieldParameterInfo = fieldParameterInfo;
      this.fieldParameterRegex = new HashMap<>();
      this.responseStatus = responseStatus;
      this.hasPathExplosion = hasPathExplosion;
      this.isEndpointMethod = true;
      this.methodHierarchies = new ArrayList<>(); // Initialize to avoid null pointer

      // Assign the new fields
      this.methodSignature = methodSignature;
      this.consumes = consumes;
      this.produces = produces;
      this.allParameters = allParameters;
  }

  public EndPointMethodInfo(EndPointMethodInfo other) {
    this.method = other.method;
    this.name = other.name;
    this.className = other.className;
    this.requestMethod = new ArrayList<>(other.requestMethod);
    this.parameterInfo = new ArrayList<>(other.parameterInfo);
    this.methodMappingPath = new ArrayList<>(other.methodMappingPath);
    this.classMappingPath = new ArrayList<>(other.classMappingPath);
    this.fieldParameterInfo = new ArrayList<>(other.fieldParameterInfo);
    this.fieldParameterRegex = new HashMap<>(other.fieldParameterRegex);
    this.responseStatus = other.responseStatus;
    this.hasPathExplosion = other.hasPathExplosion;
    this.parentResourceMethod = new ArrayList<>(other.parentResourceMethod);
    this.methodHierarchies = new ArrayList<>();
    this.methodSignature = other.methodSignature;
    this.consumes = new ArrayList<>(other.consumes);
    this.produces = new ArrayList<>(other.produces);
    this.allParameters = new ArrayList<>(other.allParameters);
    this.methodIdentifiersInfo = other.methodIdentifiersInfo;
    this.isEndpointMethod = other.isEndpointMethod;
    this.allPaths = null;
    this.allPathPathParamOpTriple = null;
  }
  // gets all path parameters
  public List<EndPointParamInfo> getPathParams() {
    return this.parameterInfo.stream().filter(pI-> pI.in==paramLoction.path).collect(Collectors.toList());
//      return this.parameterInfo.stream().collect(Collectors.toList());
  }
  
  public ArrayList<Pair<String, ArrayList<EndPointParamInfo>>> getMappingPathAndParentPathParams() {
    if(this.allPaths!=null){
      return this.allPaths;
    }

    TreeSet<Pair<String, ArrayList<EndPointParamInfo>>> cps=new TreeSet<>();
    ArrayList<ArrayList<String>> parentHierarchies = new ArrayList<>();
    for(String classMapping: this.classMappingPath){
      cps.add(Pair.of(classMapping, new ArrayList<>()));
      parentHierarchies.add(new ArrayList<>()) ;
    }


    if(!parentResourceMethod.isEmpty()){
      for(EndPointMethodInfo parentResourceEP: parentResourceMethod){
        ArrayList<Pair<String, ArrayList<EndPointParamInfo>>> parentsMapping = parentResourceEP.getMappingPathAndParentPathParams();
        ArrayList<ArrayList<String>> currParentHierarchies = parentResourceEP.methodHierarchies;
        List<EndPointParamInfo> parentPathParams = parentResourceEP.getPathParams();

        if(parentPathParams.isEmpty()){
          cps.addAll(parentsMapping);
        }
        else{
          for(Pair<String, ArrayList<EndPointParamInfo>> pM: parentsMapping){
            ArrayList<EndPointParamInfo> pathParms=new ArrayList<>(pM.getRight());
            pathParms.addAll(parentPathParams);
            // why adding parentPathParams here, alreaady shoould be in parentMapping ?
            cps.add(Pair.of(pM.getLeft(), pathParms));
          }
        }

        for (ArrayList<String> currParentHierarchy : currParentHierarchies) {
          ArrayList<String> newHierarchy = new ArrayList<>(currParentHierarchy);
          parentHierarchies.add(newHierarchy);
        }

      }
    }


    if(cps.isEmpty()){
      cps.add(Pair.of("", new ArrayList<>()));
      parentHierarchies.add(new ArrayList<>());
    }



    ArrayList<String> mps=new ArrayList<>(methodMappingPath);
    if(mps.isEmpty()){
      mps.add("");
    }

    ArrayList<Pair<String, ArrayList<EndPointParamInfo>>> mappingPaths=new ArrayList<>();
    ArrayList<ArrayList<String>> allHierarchies=new ArrayList<>();

    for(Pair<String, ArrayList<EndPointParamInfo>> cp: cps){
      for(String mp: mps){

        /// TODO: use regex replace
        String path=String.format("%s/%s",cp.getLeft(),mp).replaceAll("//", "/").replaceAll("//", "/");
        if(!path.equals("/") && path.charAt(path.length()-1)=='/'){
          path=path.substring(0, path.length()-1);
        }

        ArrayList<EndPointParamInfo> fieldPathParams=new ArrayList<>();

        Matcher m1=pathParamPattern.matcher(path);

        while (m1.find()) {
          String pName=m1.group(1);

          if(! this.parameterInfo.stream().anyMatch(ep-> ep.name.equals(pName))
          && ! cp.getRight().stream().anyMatch(ep -> ep.name.equals(pName))){
            Optional<EndPointParamInfo> p1=this.fieldParameterInfo.stream().filter(ep->ep.name.equals(pName)).findFirst();

            if(p1.isPresent()){
              fieldPathParams.add(p1.get());
              logger.debug(String.format("Found path parameter %s of %s", pName, path));
            }
            else{
              fieldPathParams.add(new EndPointParamInfo(pName, 0, true,  paramLoction.path, null, null));
              logger.debug(String.format("Failed to locate path parameter %s of %s", pName, path));
            }
          }
          
        }

        Matcher m2=pathParamPatternWithRegex.matcher(path);
        StringBuilder sb = new StringBuilder();

        while (m2.find()) {
          String[] pSecs=m2.group(1).split(":", 2);

          assert pSecs.length==2;

          String pName=pSecs[0];
          String pReg=pSecs[1];

          m2.appendReplacement(sb, String.format("{%s}", pName));

          if(! this.parameterInfo.stream().anyMatch(ep-> ep.name.equals(pName))
          && ! cp.getRight().stream().anyMatch(ep -> ep.name.equals(pName))){
            Optional<EndPointParamInfo> p1=this.fieldParameterInfo.stream().filter(ep->ep.name.equals(pName)).findFirst();

            if(p1.isPresent()){
              fieldPathParams.add(p1.get());
              logger.debug(String.format("Found path parameter %s of %s", pName, path));

              this.fieldParameterRegex.put(p1.get(), pReg);

            }
            else{
              EndPointParamInfo t1=new EndPointParamInfo(pName, 0, true,  paramLoction.path, null, null);
              fieldPathParams.add(t1);

              logger.debug(String.format("Failed to locate path parameter %s of %s", pName, path));

              this.fieldParameterRegex.put(t1, pReg);
            }
          }
        }

        m2.appendTail(sb);

        String cleanPath=sb.toString();

        ArrayList<EndPointParamInfo> requiredPathParams=new ArrayList<>(cp.getRight());
        requiredPathParams.addAll(fieldPathParams);

        mappingPaths.add(Pair.of(cleanPath, requiredPathParams));

      }
    }


    for (ArrayList<String> hierarchy : parentHierarchies){
      for(String mp: mps){
        ArrayList<String> newHierarchy = new ArrayList<>(hierarchy);
        newHierarchy.add(name);
        allHierarchies.add(newHierarchy);
      }
    }
    this.allPaths=mappingPaths;
    this.methodHierarchies = allHierarchies;

    return mappingPaths;
  }

  // just adds request methods to the path
  public ArrayList<Triple<String, ArrayList<EndPointParamInfo>, String>> getPathAndParentPathParamAndOpTuple(){
    if(this.allPathPathParamOpTriple!=null){
      return this.allPathPathParamOpTriple;
    }

    // assert (EPInfo.requestMethod.size()>=1);

    if(this.requestMethod.isEmpty() || this.isEndpointMethod==false){
      //System.out.println("No request method or not an endpoint method for " + this.name + " in " + this.method.getDeclaringClass().getName());
      this.allPathPathParamOpTriple=new ArrayList<>();
      this.methodHierarchies = new ArrayList<>() ;
      return this.allPathPathParamOpTriple;
    }

    ArrayList<Pair<String, ArrayList<EndPointParamInfo>>> mappings=this.getMappingPathAndParentPathParams();

    ArrayList<Triple<String, ArrayList<EndPointParamInfo>, String>> allPathsBound=new ArrayList<>();

    for(Pair<String, ArrayList<EndPointParamInfo>> pathPathParam: mappings){    
      // if(path.equals("/contributors")){
      //   logger.debug(path);
      // }

      for(String rm: this.requestMethod){
        allPathsBound.add(Triple.of(pathPathParam.getLeft(), pathPathParam.getRight(),rm));
      }
    }
    
    this.allPathPathParamOpTriple=allPathsBound;
    
    return allPathsBound;
  }


//  public ArrayList<ArrayList<String>> getHierarchies(){
//    if (this.methodHierarchies != null){
//      System.out.println("method " + this.name + " already has hierarchies");
//      return this.methodHierarchies ;
//    }
//
//    if (this.parentResourceMethod.isEmpty()){
//      ArrayList<String> hierarchy = new ArrayList<>();
//        hierarchy.add(this.name);
//      ArrayList<ArrayList<String>> hierarchies = new ArrayList<>();
//      hierarchies.add(hierarchy) ;
//      this.methodHierarchies = hierarchies ;
//      return hierarchies;
//    }
//
////    // print all parent
////    for(EndPointMethodInfo parent : this.parentResourceMethod){
////      System.out.println("parent " + parent.name);
////    }
//
//    ArrayList<ArrayList<String>> hierarchies = new ArrayList<>();
//    for(EndPointMethodInfo parent : this.parentResourceMethod){
//      ArrayList<ArrayList<String>> parentHierarchies = parent.getHierarchies();
//      for(ArrayList<String> parentHierarchy : parentHierarchies){
//        ArrayList<String> newHierarchy = new ArrayList<>(parentHierarchy);
//        newHierarchy.add(this.name);
//        hierarchies.add(newHierarchy);
//      }
//    }
//    this.methodHierarchies = hierarchies;
//    // print all hierarchy
////    for(ArrayList<String> hierarchy : hierarchies){
////      System.out.println("hierarchy " + hierarchy);
////    }
//    return hierarchies;
//  }

  public JSONObject toJSON() {
      // This method's logic depends on how you want to structure the final JSON.
      // The goal is to serialize all the raw data for the Python layer to process.
      // Here is a comprehensive implementation.
      JSONObject toRet = new JSONObject();

      // Existing logic to get endpoints (paths and http methods)
      ArrayList<Triple<String, ArrayList<EndPointParamInfo>, String>> endpoints = this.getPathAndParentPathParamAndOpTuple();
      JSONArray endpointsArray = new JSONArray();
      for (Triple<String, ArrayList<EndPointParamInfo>, String> endpoint : endpoints) {
          JSONObject endpointObject = new JSONObject();
          endpointObject.put("path", endpoint.getLeft());
          endpointObject.put("httpMethod", endpoint.getRight());
          // Include JAX-RS annotated parameters
          JSONArray paramsArray = new JSONArray();
          for (EndPointParamInfo param : endpoint.getMiddle()) {
              paramsArray.add(param.toJSON());
          }
          endpointObject.put("parameters", paramsArray);
          endpointsArray.add(endpointObject);
      }
      toRet.put("endpoints", endpointsArray);

      // --- Add all the other important fields ---
      toRet.put("name", this.name);
      toRet.put("className", this.className);
      
      // --- Add the NEWLY ADDED fields ---
      toRet.put("signature", this.methodSignature);

      JSONArray consumesArray = new JSONArray();
      if (this.consumes != null) {
          consumesArray.addAll(this.consumes);
      }
      toRet.put("consumes", consumesArray);

      JSONArray producesArray = new JSONArray();
      if (this.produces != null) {
          producesArray.addAll(this.produces);
      }
      toRet.put("produces", producesArray);

      // Add all parameters (annotated and unannotated) for full context
      JSONArray allParamsArray = new JSONArray();
      if (this.allParameters != null) {
          for (EndPointParamInfo param : this.allParameters) {
              allParamsArray.add(param.toJSON());
          }
      }
      toRet.put("allParameters", allParamsArray);
      
      // --- Serialize other existing fields ---
      JSONArray hierarchiesArray = new JSONArray();
      if (this.methodHierarchies != null) {
        for(ArrayList<String> hierarchy: this.methodHierarchies){
            JSONArray hierarchyArray = new JSONArray();
            for(String methodName: hierarchy){
                hierarchyArray.add(methodName);
            }
            hierarchiesArray.add(hierarchyArray);
        }
      }
      toRet.put("hierarchies", hierarchiesArray);

      JSONArray parentMethodsArray = new JSONArray();
      for(EndPointMethodInfo parentMethod: this.parentResourceMethod){
          JSONObject parentMethodObject = new JSONObject();
          parentMethodObject.put("name", parentMethod.name);
          parentMethodsArray.add(parentMethodObject);
      }
      toRet.put("parentMethods", parentMethodsArray);

      return toRet;
  }

  public static ArrayList<String> extractNames(String path) {
    ArrayList<String> names = new ArrayList<>();
    Pattern pattern = Pattern.compile("\\{(.*?)}");
    Matcher matcher = pattern.matcher(path);

    while (matcher.find()) {
      names.add(matcher.group(1));
    }
    return names ;
  }

  public static ArrayList<EndPointParamInfo> getParams(List<String> names) {
    ArrayList<EndPointParamInfo> params = new ArrayList<>();
    int index = 0;

    for (String name : names) {
      EndPointParamInfo param = new EndPointParamInfo(
              name,                        // name
              index++,                    // index (incrementing)
              true,                       // required
              paramLoction.path,          // in = "path"
              null,                       // defaultValue
              RefType.v("java.lang.String")                // type (you can customize this if needed)
      );
      params.add(param);
    }

    return params;
  }


  }
