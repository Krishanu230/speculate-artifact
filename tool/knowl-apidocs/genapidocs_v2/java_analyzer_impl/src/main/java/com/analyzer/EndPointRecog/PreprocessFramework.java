package com.analyzer.EndPointRecog;

import java.util.*;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Stream;
import java.util.stream.Collector;
import java.util.stream.Collectors;


import soot.Scene;
import soot.SootClass;
import soot.SootField;
import soot.SootMethod;
import soot.options.Options;
import soot.plugins.SootPhasePlugin;
import soot.tagkit.AnnotationArrayElem;
import soot.tagkit.AnnotationBooleanElem;
import soot.tagkit.AnnotationClassElem;
import soot.tagkit.AnnotationElem;
import soot.tagkit.AnnotationEnumElem;
import soot.tagkit.AnnotationIntElem;
import soot.tagkit.AnnotationStringElem;
import soot.tagkit.AnnotationTag;
import soot.tagkit.SignatureTag;
import soot.tagkit.Tag;
import soot.tagkit.VisibilityAnnotationTag;
import soot.tagkit.VisibilityParameterAnnotationTag;
import soot.util.Chain;
import soot.Type;
import soot.dava.internal.AST.ASTTryNode.container;
import soot.Local;
import soot.Body;
import soot.toolkits.scalar.*;
import soot.toolkits.graph.DirectedGraph;
import soot.toolkits.graph.ExceptionalUnitGraph;
import soot.toolkits.graph.UnitGraph;
import soot.jimple.*;
import soot.jimple.internal.JIfStmt;
import soot.Printer;
import soot.RefType;
import soot.BriefUnitPrinter;
import soot.Modifier;

import org.apache.commons.lang3.tuple.Pair;
import com.analyzer.EndPointRecog.FrameworkData.FrameworkName;
import com.analyzer.EndPointRecog.ParameterAnnotation.paramLoction;
//import com.analyzer.EndPointRecog.CodeAnalysedClassInfo ;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;




public class PreprocessFramework {

  public transient FrameworkData frameworkData;
  public ArrayList<EndPointMethodInfo> endPointMethodData;

  public static GetIdentifiersInfo getIdentifiersInfo;

  public static ArrayList<ClassIdentifersInfo> classesIdentifersInfo = new ArrayList<>();

  private static Logger logger = LoggerFactory.getLogger(PreprocessFramework.class);
    
  public PreprocessFramework(FrameworkData frameworkData, ArrayList<EndPointMethodInfo> endPointMethodData) {
    this.frameworkData = frameworkData;
    this.endPointMethodData = endPointMethodData;
  }

  public static FrameworkName decideFramework(Chain<SootClass> libraryClasses, Chain<SootClass> phantomClasses) {
    // libraryClasses.stream().map(c->c.getPackageName()).distinct().forEach(x->System.out.println(x));
    // phantomClasses.stream().map(c->c.getPackageName()).distinct().forEach(x->System.out.println(x));
    
    Stream<SootClass> allClasses= Stream.concat(phantomClasses.stream(), libraryClasses.stream());
    Iterator<SootClass> iter = allClasses.iterator();

    while(iter.hasNext()){
      SootClass c=iter.next();
      String p=c.getPackageName();

      for(FrameworkData d:FrameworkData.Data.values()){
        for(String s:d.packageNames){
          if(p.equals(s)){
            logger.info("The REST API uses "+d.name);
            return d.name;
          }
        }
      }
    }

    return FrameworkName.Unknown;
  }

  public static PreprocessFramework getEndPointInfo(Scene v){
    throw new UnsupportedOperationException("getEndPointInfo(Scene) is deprecated. Use getEndPointInfo(Scene, String frameworkName) instead.");
    //return getEndPointInfo(v, null, null, null);
  }

  
  public static PreprocessFramework getEndPointInfo(Scene v,  String frameworkName) {
    FrameworkName framework;
    if ("jersey".equalsIgnoreCase(frameworkName) || "jax-rs".equalsIgnoreCase(frameworkName)) {
            framework = FrameworkName.JAX;
    } else if ("spring".equalsIgnoreCase(frameworkName)) {
            framework = FrameworkName.Spring;
    } else {
            throw new RuntimeException("Unsupported framework specified: " + frameworkName);
    }
        
    System.out.println("[DIAGNOSTIC] Using specified framework: " + framework.name());

    // get all classes
    Chain<SootClass> appClasses=v.getApplicationClasses();
    Chain<SootClass> libClasses=v.getLibraryClasses();
    Chain<SootClass> phantomClasses=v.getPhantomClasses();

    // get framework
    // System.out.println("[DIAGNOSTIC] Starting framework detection...");
    // FrameworkName framework=decideFramework(libClasses, phantomClasses);
    // System.out.println("[DIAGNOSTIC] Detected Framework: " + framework.name());

    if(framework==FrameworkName.Unknown){
      throw new RuntimeException("Unknown Framework");
    }
    
    ArrayList<EndPointMethodInfo> rtv=new ArrayList<>();

    FrameworkData data=FrameworkData.Data.get(framework);


    // map for class to list of endpoint methods
    HashMap<SootClass, ArrayList<EndPointMethodInfo>> resrcClassToMethods=new HashMap<>();


    // sort application classes
    
    ArrayList<Pair<SootClass, String>> sortedAppClasses=new ArrayList<>();
    
    for(SootClass c: appClasses){
      sortedAppClasses.add(Pair.of(c, c.getName()));
    }
    sortedAppClasses.sort((b,a)->a.getRight().compareTo(b.getRight()));

    for(Pair<SootClass, String> p: sortedAppClasses){

      SootClass c=p.getLeft();
      //System.out.println("SOOT_DEBUG: Processing class: " + c.getName()); 
      // if(excludedPackageName!=null && !excludedPackageName.equals(c.getPackageName())){
      //   continue;
      // }

      // if(excludedClassName!=null && !excludedClassName.equals(c.getShortName())){
      //   continue;
      // }

      // if(c.getShortName().equals("TracksResource")){
      //   logger.info("analyzing TracksResource");
      // }

      // finding paths that point to this class
      VisibilityAnnotationTag cTags= (VisibilityAnnotationTag) c.getTag("VisibilityAnnotationTag");

      ArrayList<String> classPath=new ArrayList<>();
      ArrayList<EndPointParamInfo> fieldPathParams=new ArrayList<>();

      if(cTags != null){
        ArrayList<AnnotationTag> classAnnos = cTags.getAnnotations();
        for(AnnotationTag t: classAnnos){
          ClassMethodAnnotation CMAnno = data.classAnnotations.get(t.getType());

          if(CMAnno != null){
            classPath.addAll(CMAnno.getPathFrom(t));
          }
        }
      }

      // processing fields of class
      if(!data.fieldAnnotations.isEmpty()){
        for(SootField f: c.getFields()){
          VisibilityAnnotationTag fieldTag=(VisibilityAnnotationTag) f.getTag("VisibilityAnnotationTag");
          
          if(fieldTag==null){
            continue;
          }
  
          ArrayList<VisibilityAnnotationTag> fieldAnnos=new ArrayList<>(List.of(fieldTag));
          List<Type> fieldType=List.of(f.getType());
          
          ArrayList<EndPointParamInfo> fieldInfo=getAnnotatedParam(fieldAnnos, data.fieldAnnotations, fieldType);

          if(!fieldInfo.isEmpty()){
            fieldPathParams.add(fieldInfo.get(0));

            logger.debug(String.format("Found annotated field %s in %s", f.getName(), c.getName()));
          }
        }
      }

      // new addition start
      ArrayList<FieldInfo> fieldsInfo =  getAllFieldInfo(c) ;
      ArrayList<AnnotationInfo> classAnnotations = getAllClassAnnotations(c);
      ArrayList<String> parentClasses = getParentClasses(c);

      SignatureTag signatureTag = (SignatureTag) c.getTag("SignatureTag");
      String classSignature = (signatureTag != null) ? signatureTag.getSignature() : null;

      // new addition end

      try{

        for(SootMethod m:c.getMethods()){
          if ((m.getModifiers() & Modifier.VOLATILE) != 0) {
            continue;
          }
          //System.out.println("[DIAGNOSTIC]     -> Analyzing method: " + m.getName());
          // if(excludedMethodName!=null && !excludedMethodName.equals(m.getName())){
          //   continue;
          // }

          VisibilityAnnotationTag tags = (VisibilityAnnotationTag) m.getTag("VisibilityAnnotationTag");
          Boolean isEndpointMethod=true; 
          if(tags==null){
            //System.out.println("No VisibilityAnnotationTag for method "+m.getName()+" in class "+c.getName());
            /*
            * respector ignores methods without VisibilityAnnotationTag
            * we dont ignore since we need non endpoint methods also 
            * however if an endpoint method inherits annotations from a parent class it will be counted as non endpoint method (better than ignoring :) )
            */
            isEndpointMethod = false;
          }

          ArrayList<String> requestMethod=new ArrayList<>();
          ArrayList<String> methodPath=new ArrayList<>();
          ArrayList<String> consumes = new ArrayList<>();
          ArrayList<String> produces = new ArrayList<>();
          int responseStatus=200;

          boolean hasMethodAnnotationsNoSkip=false;

          boolean hasPathExplosion=false;

          if (tags != null){
            for(AnnotationTag mTag: tags.getAnnotations()){
              String annoType = mTag.getType();

              if(
                // annoType.equals("Lorg/respector/SkipEndPointForProfile;")|| 
                annoType.equals("Lorg/respector/SkipEndPointForPathExplosion;")
                ){
                hasPathExplosion=true;
                continue;
              }

              ClassMethodAnnotation CMAnno = data.methodAnnotations.get(annoType);

              if(CMAnno != null){
                hasMethodAnnotationsNoSkip=true;
                
                methodPath.addAll(CMAnno.getPathFrom(mTag));

                requestMethod.addAll(CMAnno.getRequestMethodFrom(mTag));
              }

              ClassMethodAnnotation CRAnno = data.responseStatusAnnotations.get(annoType);
              if(CRAnno!=null){
                Integer rtStatus=CRAnno.getResponseStatus(mTag, data.nameToResponse);
                if(rtStatus!=null){
                  responseStatus=rtStatus;
                }
              }

              if (annoType.equals("Ljavax/ws/rs/Consumes;") || annoType.equals("Ljakarta/ws/rs/Consumes;")) {
                for (AnnotationElem elem : mTag.getElems()) {
                  if (elem instanceof AnnotationArrayElem) {
                    AnnotationArrayElem arrayElem = (AnnotationArrayElem) elem;
                    for (AnnotationElem valueElem : arrayElem.getValues()) {
                      if (valueElem instanceof AnnotationStringElem) {
                        consumes.add(((AnnotationStringElem) valueElem).getValue());
                      }
                    }
                  } else if (elem instanceof AnnotationStringElem) {
                    consumes.add(((AnnotationStringElem) elem).getValue());
                  }
                }
              }
              if (annoType.equals("Ljavax/ws/rs/Produces;") || annoType.equals("Ljakarta/ws/rs/Produces;")) {
                for (AnnotationElem elem : mTag.getElems()) {
                  if (elem instanceof AnnotationArrayElem) {
                    AnnotationArrayElem arrayElem = (AnnotationArrayElem) elem;
                    for (AnnotationElem valueElem : arrayElem.getValues()) {
                      if (valueElem instanceof AnnotationStringElem) {
                        produces.add(((AnnotationStringElem) valueElem).getValue());
                      }
                    }
                  } else if (elem instanceof AnnotationStringElem) {
                    produces.add(((AnnotationStringElem) elem).getValue());
                  }
                }
              }
            }
          }

          if(!hasMethodAnnotationsNoSkip){
            isEndpointMethod = false ; 
            // continue;
            /*
            * same reason as above
            */
          }

          ///TODO: fix this
          if(requestMethod.isEmpty()){
            if(framework==FrameworkName.Spring){
              requestMethod.addAll(List.of("get", "post", "head", "options", "put", "patch", "delete", "trace"));
            }
          }

          VisibilityParameterAnnotationTag paramTags=(VisibilityParameterAnnotationTag) m.getTag("VisibilityParameterAnnotationTag");
          ArrayList<EndPointParamInfo> paramInfo;
          if(paramTags==null){
            paramInfo=new ArrayList<>();
          }
          else{

            ArrayList<VisibilityAnnotationTag> paramAnnos=paramTags.getVisibilityAnnotations();

            List<Type> paramTypes= m.getParameterTypes();
            
            paramInfo=getAnnotatedParam(paramAnnos, data.paramAnnotations, paramTypes);
            // print all params
            // for (EndPointParamInfo param: paramInfo){
            //   System.out.println(param.name + " " + param.type);
            // }
            // DONE: no argument end point?
            // keep them
            // if(paramInfo.isEmpty()){
              // continue;
            // }
          }
          
          ArrayList<EndPointParamInfo> allParameters = new ArrayList<>();
          List<Type> allParamTypes = m.getParameterTypes();
          for (int i = 0; i < allParamTypes.size(); i++) {
              allParameters.add(new EndPointParamInfo("param" + i, i, null, null, null, allParamTypes.get(i)));
          }

          // new addition start
          MethodIdentifiersInfo methodIdentifiersInfo = getIdentifiersInfo.extractIdentifiersFromMethod(m,c);
          

          EndPointMethodInfo EPInfo = new EndPointMethodInfo(
              m, m.getName(), c.getName(), requestMethod, paramInfo,
              methodPath, classPath, fieldPathParams, responseStatus, hasPathExplosion,
              m.getSignature(), consumes, produces, allParameters
          );

          EPInfo.methodIdentifiersInfo = methodIdentifiersInfo;
          EPInfo.isEndpointMethod = isEndpointMethod;
          // new addition end
          rtv.add(EPInfo);

          ArrayList<EndPointMethodInfo> epms = resrcClassToMethods.computeIfAbsent(c, x-> new ArrayList<>());
          epms.add(EPInfo);
        }
      } catch (Exception e) {
        logger.error("PreprocessFramework: Error processing class " + c.getName() + ": " + e.getMessage());
      }

      // new addition start
      ArrayList<EndPointMethodInfo> epms = resrcClassToMethods.computeIfAbsent(c, x-> new ArrayList<>());
      ClassIdentifersInfo classIdentifersInfo = new ClassIdentifersInfo(
        epms,          // ArrayList<EndPointMethodInfo>
        c,             // <<<< THIS SHOULD BE THE SootClass OBJECT 'c'
        fieldsInfo,    // ArrayList<FieldInfo>
        fieldPathParams, // ArrayList<EndPointParamInfo>
        parentClasses, // ArrayList<String>
        classSignature,       
        classAnnotations, // ArrayList<AnnotationInfo>
        classPath      // ArrayList<String>
    );
      classesIdentifersInfo.add(classIdentifersInfo);
      //.out.println("Added class: " + classIdentifersInfo.className + " with " + classIdentifersInfo.functions.size() + " functions.");
      // new addition end
    }

    linkSubResources(resrcClassToMethods);

    return new PreprocessFramework(data, rtv);
  }

  public static void linkSubResources(HashMap<SootClass, ArrayList<EndPointMethodInfo>> resrcClassToMethods) {
    for(Map.Entry<SootClass, ArrayList<EndPointMethodInfo>> kv: resrcClassToMethods.entrySet()){
      SootClass c=kv.getKey();
      ArrayList<EndPointMethodInfo> endPoints=kv.getValue();
      for(EndPointMethodInfo ep: endPoints){
        if (!ep.isEndpointMethod){
          /*
           * not involved in linking sub resources since not an endpoint method
           */
          continue;
        }
        SootMethod m=ep.method;

        Type rType = m.getReturnType();

        if(rType instanceof RefType){
          RefType refRtv=(RefType) rType;

          SootClass clz=refRtv.getSootClass();

          if(clz.equals(c)){
            logger.error(String.format("method %s returns its own class %s", m.getSignature(), c.getName()));
            continue;
          }

          if(resrcClassToMethods.containsKey(clz)){
            for(EndPointMethodInfo subEP: resrcClassToMethods.get(clz)){
              subEP.parentResourceMethod.add(ep);
            }
          }
        }
      }
    }
  }

  public static boolean endpointAnnoCheck(AnnotationTag tag, Map<String,ClassMethodAnnotation> methodAnnotations){   
    return methodAnnotations.containsKey(tag.getType());
  }
  

  public static ArrayList<EndPointParamInfo> getAnnotatedParam(ArrayList<VisibilityAnnotationTag> tagList, Map<String,ParameterAnnotation> paramAnnotations, List<Type> paramTypes) {
    ArrayList<EndPointParamInfo> rtv=new ArrayList<>();
    
    int len=tagList.size();
    for(int i=0;i<len;++i){
      VisibilityAnnotationTag tag=tagList.get(i);

      if(tag==null){
        continue;
      }

      String name=null;
      Boolean required=null;
      paramLoction in=null;
      String defaultValue=null;

      boolean hasParamAnnotation=false;

      for(AnnotationTag pTag: tag.getAnnotations()){
        String type1=pTag.getType();
        ParameterAnnotation PAnno = paramAnnotations.get(type1);

        if(PAnno != null){
          hasParamAnnotation=true;

          if(name==null){
            name=PAnno.getNameFrom(pTag);
          }

          if(required==null){
            required=PAnno.getRequiredFrom(pTag);
          }

          if(in==null){
            in=PAnno.getInFrom(pTag);
          }

          if(defaultValue==null){
            defaultValue=PAnno.getDefaultValueFrom(pTag);
          }

        }
      }

      if(!hasParamAnnotation){
        continue;
      }

      // if(required==null){
      //   required=true;
      // }
      if(paramLoction.path.equals(in)){
        required=true;
      }
      if(name==null){
        name="";
      }
      
      rtv.add(new EndPointParamInfo(name, i, required, in, defaultValue, paramTypes.get(i)));
      
    }

    return rtv;
  }


  private static ArrayList<FieldInfo> getAllFieldInfo(SootClass sootClass) {
        ArrayList<FieldInfo> fieldInfoList = new ArrayList<>();

        for (SootField field : sootClass.getFields()) {
            String name = field.getName();
            Type type = field.getType(); // This is soot.Type
            String typeString = type.toString(); // Default

            // Attempt to get generic signature from SignatureTag
            SignatureTag signatureTag = (SignatureTag) field.getTag("SignatureTag");
            if (signatureTag != null) {
              String genericSignature = signatureTag.getSignature();
              String parsedGenericType = parseSootGenericSignature(genericSignature); // Use the parser
              if (parsedGenericType != null) {
                  typeString = parsedGenericType;
              } else {
                  // If parser returns null (e.g. for primitives like "I", "Z" in signature),
                  // field.getType().toString() might be better.
                  // Or, handle primitive descriptors in parseSootGenericSignature
                  // For now, log and use default if parsing fails to produce something.
                  logger.debug("Field " + field.getDeclaringClass().getName() + "." + name +
                               " has SignatureTag '" + genericSignature +
                               "' but parseSootGenericSignature returned null. Using default type: " + typeString);
              }
            }
            // else { System.out.println("DEBUG: Field " + name + " has no SignatureTag. Type from getType(): " + type.toString()); }


            // Create field info - now passing the potentially more detailed typeString
            // The FieldInfo constructor takes soot.Type, but its toJSON will use our derived typeString.
            // It might be better to pass the string directly if FieldInfo is primarily for JSON.
            // For now, let's modify FieldInfo to accept this string or make its toJSON smarter.

            // Option A: Modify FieldInfo to store the detailed string.
            // FieldInfo fieldInfo = new FieldInfo(name, type, typeString); // (Requires FieldInfo constructor change)

            // Option B: Let FieldInfo handle its own toString() logic for type.
            // We've tried to make FieldInfo's type string generation smarter,
            // but the real generic info comes from the field's SignatureTag, not just field.getType().
            // So, we *must* extract the detailed type string here and pass it,
            // or make FieldInfo aware of SootField to get its tag.
            // Let's pass the string for simplicity.

            // Create field info (passing the best type string we have)
            FieldInfo fieldInfo = new FieldInfo(name, type); // Original constructor
            // We'll override the type in its JSON representation.

            // To ensure the JSON output from FieldInfo uses the detailed type string:
            // We can't easily modify FieldInfo.toJSON() to take an extra parameter from here.
            // So the best place to ensure the right string is used is when creating the JSON for the field.
            // This means `ClassIdentifersInfo.toJSON()` needs to be smarter when serializing `FieldInfo`.
            // This is getting complicated.

            // --- SIMPLER APPROACH: Store the detailed type string directly in FieldInfo ---
            // Let's modify FieldInfo to hold both soot.Type and the best string representation.

            fieldInfoList.add(fieldInfo); // Original fieldInfo is added

            // The crucial part is what goes into the JSON.
            // Let's modify ClassIdentifiersInfo.toJSON() for this.
        }
        return fieldInfoList;
    }

    // Helper to parse Soot's generic signature format to a Java-like format
    // This is a simplified parser and might need to be made more robust.
    public static String sootDescriptorToJavaFQN(String descriptor) {
    if (descriptor == null) return null;
    String result = descriptor;
    if (result.startsWith("L") && result.endsWith(";")) {
        result = result.substring(1, result.length() - 1);
    }
    return result.replace('/', '.');
}

public static String parseSootGenericSignature(String sig) {
    if (sig == null) return null;

    // Handles simple non-generic cases from SignatureTag too, e.g. "Ljava/lang/String;"
    if (!sig.contains("<")) { // Not a generic signature, but might be a descriptor
        if (sig.startsWith("L") && sig.endsWith(";")) {
            return sootDescriptorToJavaFQN(sig);
        }
        // Could be a primitive descriptor like "I" for int, "Z" for boolean.
        // Soot's field.getType().toString() usually handles primitives better.
        // This function is primarily for complex/generic signatures.
        // If sig is already like "int", "java.lang.String", return it.
        if (!sig.contains("/") && !sig.startsWith("[")) { // Heuristic for already clean types
            return sig;
        }
        return null; // Or return sig if it might be a primitive descriptor
    }

    // Example: "Ljava/util/Set<Lorg/javiermf/features/models/Feature;>;"
    // Example: "Ljava/util/Map<Ljava/lang/String;Lorg/javiermf/features/models/Product;>;"
    // Example for array of generics: "[Ljava/util/List<Ljava/lang/String;>;"

    StringBuilder javaLikeSig = new StringBuilder();
    Stack<Boolean> inGenericParam = new Stack<>(); // To handle nested generics

    for (int i = 0; i < sig.length(); i++) {
        char c = sig.charAt(i);
        switch (c) {
            case 'L': // Start of a class name
                int semicolon = sig.indexOf(';', i);
                if (semicolon != -1) {
                    String descriptor = sig.substring(i + 1, semicolon);
                    javaLikeSig.append(descriptor.replace('/', '.'));
                    i = semicolon; // Move parser past the semicolon
                } else {
                    javaLikeSig.append(c); // Should not happen in valid sigs
                }
                break;
            case '<':
                inGenericParam.push(true);
                javaLikeSig.append('<');
                break;
            case '>':
                if (!inGenericParam.isEmpty()) inGenericParam.pop();
                javaLikeSig.append('>');
                break;
            case ';': // Semicolon for class types, or separating params in method sigs
                if (inGenericParam.isEmpty()) {
                    // This semicolon likely ends the whole signature, or separates method params.
                    // If it's the end of the whole signature, we might not want to append it.
                    // If it's separating map K,V then we need it as a comma.
                    // This part is tricky without a full signature parser.
                    // For now, let's assume it's an argument separator for maps or end.
                    // If the next char is not '>', it's likely a map separator.
                    if (i + 1 < sig.length() && sig.charAt(i+1) != '>') {
                        javaLikeSig.append(", "); // Convert to comma for map-like structures if not end
                    }
                } else {
                     javaLikeSig.append(';'); // Keep if inside generic params (e.g. array of L...;)
                }
                break;
            case '[':
              javaLikeSig.append(c);
              break; // ADDED
            case '/':
              // If still needed after L...; processing, this logic might be flawed.
              // For now, ensure break.
              javaLikeSig.append(c);
              break; // ADDED
            default:
                javaLikeSig.append(c);
                break;
        }
    }
    // The above parser is still too simplistic for robust generic signature parsing.
    // Soot's SignatureTag.getSignature() often gives a very JVM-internal format.
    // A more reliable way is to use Soot's own parsing utilities if available or
    // focus on getting the Type object for each part of the signature and calling toString() on those.

    // Fallback to a simpler regex for common List/Set/Map cases if the above is too complex to debug quickly
    // This is less robust than a proper parser.
    Pattern commonGenericPattern = Pattern.compile("L([^<;]+)<(.*?)>;");
    Matcher m = commonGenericPattern.matcher(sig);
    if (m.find()) {
        String outer = m.group(1).replace('/', '.');
        String inner = m.group(2);
        List<String> innerTypes = new ArrayList<>();
        // Recursively parse inner types (this needs a better split for Map K,V)
        // For now, a simple split by ';' which is not robust for nested generics
        String[] parts = inner.split(";");
        for (String part : parts) {
            if (part.isEmpty()) continue;
            String parsedPart = parseSootGenericSignature(part + (part.endsWith(";") ? "" : ";")); // Ensure ; for recursion
            if(parsedPart == null && part.startsWith("L")) parsedPart = sootDescriptorToJavaFQN(part+";");
            else if (parsedPart == null) parsedPart = part.replace('/', '.'); // Fallback

            if (parsedPart != null) innerTypes.add(parsedPart);
        }
        return outer + "<" + String.join(", ", innerTypes) + ">";
    }

    // If it's just a descriptor like "Ljava/lang/String;"
    if (sig.startsWith("L") && sig.endsWith(";")) {
        return sootDescriptorToJavaFQN(sig);
    }

    return sig; // Fallback if no specific parsing applies
}

  /**
   * Parses an AnnotationTag into the AnnotationInfo structure
   * @param annotationTag The AnnotationTag to parse
   * @return An AnnotationInfo object
   */
  public static AnnotationInfo parseAnnotationTag(AnnotationTag annotationTag) {
    String typeDescriptor = annotationTag.getType();
    AnnotationInfo annotationInfo = new AnnotationInfo(typeDescriptor);

    for (AnnotationElem elem : annotationTag.getElems()) {
        String name = elem.getName();
        String kind = String.valueOf(elem.getKind());

        if (elem instanceof AnnotationStringElem) {
            annotationInfo.elements.add(new AnnotationElementInfo(name, ((AnnotationStringElem) elem).getValue(), kind));
        } else if (elem instanceof AnnotationIntElem) {
            annotationInfo.elements.add(new AnnotationElementInfo(name, String.valueOf(((AnnotationIntElem) elem).getValue()), kind));
        } else if (elem instanceof AnnotationBooleanElem) {
            annotationInfo.elements.add(new AnnotationElementInfo(name, String.valueOf(((AnnotationBooleanElem) elem).getValue()), kind));
        } else if (elem instanceof AnnotationEnumElem) {
            annotationInfo.elements.add(new AnnotationElementInfo(name, ((AnnotationEnumElem) elem).getConstantName(), kind));
        } else if (elem instanceof AnnotationClassElem) {
            annotationInfo.elements.add(new AnnotationElementInfo(name, ((AnnotationClassElem) elem).getDesc(), kind));
        } else if (elem instanceof soot.tagkit.AnnotationAnnotationElem) { // *** FIX #1: CHECK FOR THIS SPECIFIC TYPE ***
            // This handles a single nested annotation, like content = @Content(...)
            soot.tagkit.AnnotationAnnotationElem nestedAnnotationElem = (soot.tagkit.AnnotationAnnotationElem) elem;
            AnnotationTag nestedTag = nestedAnnotationElem.getValue(); // Get the nested AnnotationTag
            AnnotationInfo nestedInfo = parseAnnotationTag(nestedTag); // *** RECURSIVE CALL ***
            annotationInfo.elements.add(new AnnotationElementInfo(name, nestedInfo, kind));
        } else if (elem instanceof AnnotationArrayElem) {
            AnnotationArrayElem arrayElem = (AnnotationArrayElem) elem;
            ArrayList<Object> arrayValues = new ArrayList<>();
            for (AnnotationElem innerElem : arrayElem.getValues()) {
                // Also check for nested annotations inside the array
                if (innerElem instanceof soot.tagkit.AnnotationAnnotationElem) { // *** FIX #2: CHECK INSIDE ARRAY ***
                     soot.tagkit.AnnotationAnnotationElem nestedAnnotationElem = (soot.tagkit.AnnotationAnnotationElem) innerElem;
                     arrayValues.add(parseAnnotationTag(nestedAnnotationElem.getValue())); // *** RECURSIVE CALL ***
                } else if (innerElem instanceof AnnotationStringElem) {
                    arrayValues.add(((AnnotationStringElem) innerElem).getValue());
                } else if (innerElem instanceof AnnotationIntElem) {
                    arrayValues.add(String.valueOf(((AnnotationIntElem) innerElem).getValue()));
                } else if (innerElem instanceof AnnotationBooleanElem) {
                    arrayValues.add(String.valueOf(((AnnotationBooleanElem) innerElem).getValue()));
                } else {
                    arrayValues.add(innerElem.toString()); 
                }
            }
            annotationInfo.elements.add(new AnnotationElementInfo(name, arrayValues, kind));
        } else {
            // Fallback for any unhandled types
            annotationInfo.elements.add(new AnnotationElementInfo(name, elem.toString(), kind));
        }
    }
    return annotationInfo;
}


  /**
   * Extracts all annotations from a SootClass
   * @param sootClass The SootClass to analyze
   * @return A list of AnnotationInfo objects containing all class annotations
   */
  public static ArrayList<AnnotationInfo> getAllClassAnnotations(SootClass sootClass) {
    ArrayList<AnnotationInfo> annotationList = new ArrayList<>();


    // Extract class annotations if present
    VisibilityAnnotationTag visibilityTag = (VisibilityAnnotationTag) sootClass.getTag("VisibilityAnnotationTag");

    if (visibilityTag != null) {
      for (AnnotationTag annotationTag : visibilityTag.getAnnotations()) {
        // Create annotation info
        AnnotationInfo annotationInfo = parseAnnotationTag(annotationTag);
        annotationList.add(annotationInfo);
      }
    }

    return annotationList;
  }

  /**
   *
   * gets parent class chain of a class
   * @param sootClass
   * @return
   */
  public static ArrayList<String> getParentClasses(SootClass sootClass) {
    LinkedHashSet<String> parentFqns = new LinkedHashSet<>();
    
    // Use a queue for breadth-first traversal of the hierarchy.
    Queue<SootClass> queue = new LinkedList<>();
    queue.add(sootClass);

    // Keep track of visited classes to avoid infinite loops with circular dependencies.
    Set<String> visited = new HashSet<>();
    visited.add(sootClass.getName());

    while (!queue.isEmpty()) {
        SootClass currentClass = queue.poll();

        // 1. Add the direct superclass (for classes)
        if (currentClass.hasSuperclass()) {
            SootClass superClass = currentClass.getSuperclass();
            if (superClass != null && !superClass.getName().equals("java.lang.Object")) {
                String superClassName = superClass.getName();
                if (!visited.contains(superClassName)) {
                    parentFqns.add(superClassName);
                    visited.add(superClassName);
                    queue.add(superClass);
                }
            }
        }

        // 2. Add all implemented/extended interfaces
        if (currentClass.getInterfaceCount() > 0) {
            for (SootClass superInterface : currentClass.getInterfaces()) {
                if (superInterface != null) {
                    String interfaceName = superInterface.getName();
                    if (!visited.contains(interfaceName)) {
                        parentFqns.add(interfaceName);
                        visited.add(interfaceName);
                        queue.add(superInterface);
                    }
                }
            }
        }
    }

    return new ArrayList<>(parentFqns);
  }

}
