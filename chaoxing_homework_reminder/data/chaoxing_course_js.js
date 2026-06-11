$(function () {
	var localStorage = window.localStorage;
	var baseEducation = $("#baseEducation").val();
	var superstarClass = $("#superstarClass").val();
	if(superstarClass == 0 && baseEducation == 0 && localStorage){
		var clearLocalStorage = $("#clearLocalStorage").val();
		if(clearLocalStorage == 1){
			localStorage.setItem( "newMoocVersion", 0);
		}else{
			var newMoovVersion = localStorage.getItem("newMoocVersion");
			if(newMoovVersion == 1){
				toNewCourseList();
				return;
			}
		}
	}
	
    setMainHeight();

    newFolder();
    
    fileRename();
    
    switchCourseList();
    
    fileOperation();

    $(".current").click();
});

function switchCourseList(){
	$(".course-tab").on("click", ".tab-item", function(){
		$(".tab-item").removeClass("current");
		$(this).addClass("current");
		var courseType = $(this).attr("courseType");
		$("#courseFolderId").val(0);
		$("#courseType").val(courseType);
		$("#fileList").show();
		$("#addFolder").show();
		if(courseType == 0){
			$("#addCourse").hide();
			$("#newCourse").show();
		}else{
			$("#addCourse").show();
			$("#newCourse").hide();
		}
		getCourseList(true);
	})
	
}

// 新建文件夹
function newFolder() {
	var content = "<li id=\"newDir2\">\n" +
    "<img class=\"icon-file\" src=\"/mooc2/images/file.png\"/>\n" +
    "<div class=\"name-box\">\n" +
    "<h3 class=\"file-name overHidden2 hide\">新建文件夹</h3>\n" +
    "<input type=\"text\" value=\"新建文件夹\" class=\"new-name-input\" onkeypress=\"createFolder(event)\" id=\"focusInput\">\n" +
    "</div>\n" +
    "</li>";

	$(".add-folder").on("click", function () {
	    if ($("#focusInput").length > 0) {
	        return;
	    }
	    $(this).parents(".course-list-con").find(".file-list").prepend(content);
	    $("body").scrollTop($("#fileList").offset().top);
	    $("#fileList li").eq(0).find("input").focus().select();
	})
	
	$(".file-list").on('blur','.new-name-input',function () {
        var name = $(this).val();
        name = name.replace(/<\/?[^>]+>/g,"").trim();
        realCreateFolder(name);
    })
}
function createFolder(e) {
    if (e.keyCode == 13) {
        $("#focusInput").blur();
    }
}

function realCreateFolder(name){
	 $.ajax({
         type: "post",
         url: _HOST_CP2_ + "/fileCourse/create",
         data: {
         	fileName: name
         },
         success: function (data) {//如果调用成功
            if (Number(data) <= 0) {
            	publicTips('failure', '创建失败'); 
            	return
            } 
             var content1 =
            '<li fileid="'+data+'" id="folder_'+data+'">\n' +
    	    	' <img class="icon-file" src="' + _HOST_CP2_ + '/mooc2/images/file.png" onclick="intoFolder('+data+')" />\n' +
		        '<div class="name-box">\n'+
    		    	'<h3 class="file-name overHidden2" onclick="intoFolder('+data+')">'+name+'</h3>\n'+
    		    	'<input type="text" value="'+name+'" class="rename-input hide" onkeypress="createFolder(this)">\n'+
			    ' </div>\n'+
			    '<ul class="hanlde-list" >\n'+
    			    '<li class="move-to file-rename">重命名</li>\n'+
    		    	'<li class="archive file-del">删除</li>\n'+
    	    	'</ul>\n'+
    		'</li>'
    	     $('#newDir2').remove();
             
             
        	 $("#fileList").prepend(content1);
        	 $("body").scrollTop($("#fileList").offset().top);
      	     
         }
     });
}

// 文件夹重命名
function fileRename() {
    $(".file-list").on("click", ".file-rename", function () {
        $(this).parents("li").find('.file-name').addClass('hide');
        $(this).parents('li').find('.rename-input').removeClass('hide').focus().select();
    })

    $(".file-list").on('blur','.rename-input',function () {
        var name = $(this).val();
        var oldname = $(this).parents("li").find('.file-name').text();
        $(this).addClass('hide');
        $(this).parents("li").find('.file-name').text(name).removeClass('hide');
        if (name == oldname) {
            return;
        }
        var id = $(this).parents("li").attr("fileid");
        realRenameFolder(name,id);
       
    })
}

function realRenameFolder(name,id){
     $.ajax({
         type: "post",
         url: _HOST_CP2_ + "/fileCourse/reName",
         data: {
        	 fileId: id,
        	 fileName: name
         },
         success: function (data) {//如果调用成功
             if (data == "failed") {
                 publicTips('failure', '修改名称失败');
             }
         }
     });
}


// 打开移动到弹框
function courseOperationBtn() {
    $(".course-list").on("click", ".movetobtn", function () {
    	var courseli = $(this).parents(".course");
    	var courseId = courseli.attr("courseId");
    	var clazzId = courseli.attr("clazzId");
    	var personId = courseli.attr("personId");
		var courseFolderId = $("#courseFolderId").val();

	    openFirstPagePop2( 4, 640, 480, clazzId, courseId, personId, courseFolderId, moveCourseNewFolder, ajaxMoveCourse);
    })
       
    $(".course-list").on("click", ".endCourseBtn", function () {
    	var courseli = $(this).parents(".course");
    	var courseId = courseli.attr("courseId");
    	var clazzId = courseli.attr("clazzId");
    	var personId = courseli.attr("personId");
    	
    	openFirstPagePop( 2, 440, 232, clazzId, courseId, personId, 0, updateCourseState);
    })
    
    
           
    $(".course-list").on("click", ".cancelEndCourseBtn", function () {
    	var courseli = $(this).parents(".course");
    	var courseId = courseli.attr("courseId");
    	var clazzId = courseli.attr("clazzId");
    	var personId = courseli.attr("personId");
    	
    	openFirstPagePop( 9, 440, 232, clazzId, courseId, personId, 0, updateCourseState);
    })
    
     $(".course-list").on("click", ".deleteCourseBtn", function () {
    	var courseli = $(this).parents(".course");
    	var courseId = courseli.attr("courseId");
    	var personId = courseli.attr("personId");
    	var role = $(this).attr("data");
    	var contentTip = "";
		var thisHeight = 232;
    	if(role == 2){
			thisHeight = 260;
			contentTip = "退出后，将无法查看和使用自己在本课私有文件夹下的所有资料。确认退出教学团队？";
			if (I18N) {
				contentTip = I18N.CourseTip6;
				if (I18N.language && I18N.language == "english") {
					thisHeight = 282;
				}
			}
		}
    	var btn1Text = "";
    	var btn2Text = "";
    	var weburl = location.protocol + "//" + location.hostname + "/visit/course/homepagepopup?type=1";
    	openPop({
			 weburl: weburl,
			 width: 440,
			 height: thisHeight,
			 clazzId: 0,
			 personId: personId,
			 courseId: courseId,
			 contentTip:contentTip,
			 btn1Text: btn1Text,
			 btn2Text: btn2Text,
			 type: 1,
			 _function: teacherFileCourse
		 });

    })
    
    $(".course-list").on("click", ".quitCourseBtn", function () {
    	var courseli = $(this).parents(".course");
    	var courseId = courseli.attr("courseId");
    	var clazzId = courseli.attr("clazzId");
    	var personId = courseli.attr("personId");
    	openFirstPagePop( 3, 440, 232, clazzId, courseId, personId, 0, ajaxQuitCourse);
    })
}

function fileOperation(){
	 $(".file-list").on("click", ".file-del", function () {
	        var $this = $(this);
	        var fileid = $this.parent().parents("li").attr("fileid");
	        openFirstPagePop( 6, 440, 232, 0, 0, 0, fileid, deleteFile);
	    })
}
function moveCourseNewFolder(data,name){
    var content1 =
        '<li fileid="'+data+'" id="folder_'+data+'">\n' +
	    	' <img class="icon-file" src="' + _HOST_CP2_ + '/mooc2/images/file.png" onclick="intoFolder('+data+')" />\n' +
	        '<div class="name-box">\n'+
		    	'<h3 class="file-name overHidden2" onclick="intoFolder('+data+')">'+name+'</h3>\n'+
		    	'<input type="text" value="'+name+'" class="rename-input hide" onkeypress="createFolder(this)">\n'+
		    ' </div>\n'+
		    '<ul class="hanlde-list" >\n'+
			    '<li class="move-to file-rename">重命名</li>\n'+
		    	'<li class="archive file-del">删除</li>\n'+
	    	'</ul>\n'+
		'</li>'
	     $('#newDir2').remove();
    	 $("#fileList").prepend(content1);
    	 $("body").scrollTop($("#fileList").offset().top);
}
function ajaxQuitCourse(params){
	var clazzid = params.clazzId;
    var courseid = params.courseId;
    var quitCourseCpi = params.personId;
    $.ajax({
        type: "get",
        url: _HOST_CP2_ + "/visit/doarchive/student",
        data: {
            clazzid: clazzid
        },
        dataType : "json",
        success: function (data) {
            if (data.succ) {
            	$("#course_" + courseid +"_" + clazzid).remove();
            	layer.close(params.layerindex);
            } else {
            	layer.close(params.layerindex);
                publicTips('failure', '退课失败');
            }
			closeParentMask();
        }
    });
}

function deleteFile(params){
	var fileid = params.fileId;
	$.ajax({
	    type: "post",
	    url: _HOST_CP2_ + "/fileCourse/del",
	    data: {
	    	fileId: fileid
	    },
	    success: function (data) {
	        if (data == "success") {
	        	getCourseList(false);
	            $("#folder_" + fileid).remove();
	            layer.close(params.layerindex);
	        } else if (data == "notEmpty") {
	            publicTips('failure', "文件夹中存在课程不允许删除");
	            layer.close(params.layerindex);
	        } else {
	            publicTips('failure', "删除文件夹失败");
	            layer.close(params.layerindex);
	        }
			closeParentMask();
	    }
	});
}
function ajaxMoveCourse(params) {
	var moveCourseId = params.courseId;
    var moveFileId = params.fileId;
    var movePersonId = params.personId;
    var moveClassId = params.clazzId;
    if (moveCourseId == "" || movePersonId == "" || moveClassId == "") {
        publicTips('failure', '参数错误');
        return false;
    }
    $.ajax({
        type: "get",
        url: _HOST_CP2_ + "/fileCourse/movecourseandclazz",
        data: {
        	fileId: moveFileId,
        	courseId: moveCourseId,
            clazzId: moveClassId,
            cpi: movePersonId
        },
        dataType : "json",
        success: function (data) {//如果调用成功
			if(data.sameFolder){//文件新目录和旧目录一致则直接关闭页面
				layer.close(params.layerindex);
			}else if(data.status){
				$("#course_"+moveCourseId+"_"+moveClassId).remove();
				layer.close(params.layerindex);
			}else{
				layer.close(params.layerindex);
				publicTips('failure', '移动失败');
			}
			closeParentMask();
        }
    });
}

function updateCourseState(params){
	var courseId = params.courseId;
    var personId = params.personId;
    var state = 1 ;
    if(params.type == 2){
    	state = 1;
    }else{
    	state = 0;
    }
    $.ajax({
        type: "get",
        url: _HOST_CP2_ + "/updatecoursestate",
        data: {
        	courseid: courseId,
        	cpi: personId,
        	state : state,
        },
        dataType : "json",
        success: function (data) {
            if (data.status) {
            	layer.close(params.layerindex);
              	getCourseList(false);
            } else {
            	layer.close(params.layerindex);
                publicTips('failure', data.msg);
            }
			closeParentMask();
        }
    });
}

function teacherFileCourse(params){
	var courseId = params.courseId;
    var personId = params.personId;
    $.ajax({
        type: "get",
        url: _HOST_CP2_ + "/visit/teacherfilecourse",
        data: {
        	courseId: courseId,
        	isFiled: 1,
        	cpi : personId,
        },
        dataType : "json",
        success: function (data) {
            if (data.status) {
            	$("#deleteCourseHref").show();
                $("#course_" + courseId +"_" + 0).remove();
                layer.close(params.layerindex);
            } else {
            	layer.close(params.layerindex);
                publicTips('failure', data.msg);
            }
			closeParentMask();
        }
    });
}

function getCourseList(){
	var courseFolderId = $("#courseFolderId").val();
	var courseType = $("#courseType").val();
	var courseFolderSize = $("#courseFolderSize").val();
	var baseEducation = $("#baseEducation").val();
	var superstarClass = $("#superstarClass").val();
	$.ajax({
		url : _HOST_CP2_ + "/visit/courselistdata",
		type : "post",
		data : {
			courseType : courseType,
			courseFolderId : courseFolderId,
			baseEducation : baseEducation,
			superstarClass : superstarClass,
			courseFolderSize : courseFolderSize
		},
		dataType : "html",
		success : function(data){
			$("#courselistArea").empty();
			$("#courselistArea").html(data);
			getLayer();
		    // 设置main区域的最少高度
		    setMainHeight();
		    searchCourseFa();
		    courseOperationBtn();
		}
		
	})
}

function getAllCourse(){
	
	   var courseFolderId = $("#courseFolderId").val();
	   
	   if(courseFolderId == 0){
		   $("#courseList>li").hide();
		   $("#courseNav").hide();
		   $("#addFolder").show();
	   }else{
		   $("#courseNav>.active").hide();
	   }
       $("#searchInput").val("");
       
       if ($("#courseList>li").length > 0) {
		   $("#nullCourse").hide();
           $("#courseList>li").show();
           $("#fileList>li").show();
       } else {
           $("#nullCourse").show();
       }
}
function searchCourseFa(){
    //搜索框支持enter键搜索
    $('#searchInput').on('keydown', function(e){
        if (e.which === 13) {
        	searchCourse();
        }
    });
    $("#searchBtn").click(function (){
    	searchCourse();
    })
}
//搜索
function searchCourse(){
	
	var searchName = $("#searchInput").val();
    if (searchName == "") {
    	getAllCourse();
        return;
    } 
    $("#courseList>li").hide();
    $("#fileList>li").hide();
    $("#nullCourse").hide();
    $("#courseNav li.active").text('搜索“' + searchName + '”');
    $("#courseNav").show();
   
    var count = 0;
    for (var i = 0, len = $("#courseList>li").length; i < len; i++) {
        var item = $("#courseList>li").eq(i);
        var courseName = item.find(".course-name").attr("title");
        if (courseName.indexOf(searchName) > -1) {
            item.show();
            count ++;
        }
    }
    if (count == 0) {
        $("#nullCourse").show();
    }
}

//进入文件夹的操作
function intoFolder(courseFolderId){
 	$("#courseFolderId").val(courseFolderId);
 	$("#fileList").hide();
 	$("#addFolder").hide();
 	getCourseList(true);
}


function realGetCourseList(){
	$("#courseFolderId").val(0);
	$("#fileList").show();
	$("#addFolder").show();
	getCourseList(true);
}

function publicTips(type, tip ,time,left) {
	if(typeof(time) == "undefined" || time == ""){
		time = 1500;
	}
	if(typeof(left) == "undefined" || left == ""){
		left = "45%";
	}
    $.toast({
        content: tip,
        type: type,
        time: time,
        left:left
    })
}


function clickCourseLink(courseId, enc, cpi,courseName,imageUrl) {
	addTchCourse2Client(courseId,courseName,imageUrl);

	try {
		sendCourseStatistics(courseId,enc,cpi);
	}catch (ex) {
		console.log(ex);
	}
}

function sendCourseStatistics(courseId, enc, cpi) {
    $.ajax({
        type: "get",
        url: _HOST_CP2_ + "/visit/course-statistic",
        data: {
            "courseId": courseId,
            'enc': enc,
            'cpi': cpi
        },
        success: function () {
        },
        error: function () {
        }
    });
}

$('#searchInput').on('input', function(){
    var thisVal = $(this).val();
    var dataSearchDeleteEle = $(".dataSearch_dele");
    if(thisVal === ""){
        dataSearchDeleteEle.hide()
    } else{
        dataSearchDeleteEle.show()
    }
});

$('.dataSearch_dele').on('click', function(){
	$(".dataSearch_dele").hide();
    getAllCourse();
});

function toNewCourseList() {
	var localStorage = window.localStorage;
	if(localStorage){
		localStorage.setItem( "newMoocVersion", 1);
	}
	var curMoocDomain = $("#curMoocDomian").val();
    var url = ServerHost.mooc2Domain + "/mooc2-ans/visit/interaction?moocDomain="+curMoocDomain;
    window.location.href = url;
}

function openNewCourse() {
	var baseEducation = $("#baseEducation").val();
	
	if(baseEducation == 1){
		baseEduCreateCoursePop( 440, 228);
	}else{
		openFirstPagePop( 5, 840, 564, 0, 0, 0, 0, ajaxCreateCourse);
	}
}

function baseEduCreateCoursePop(width, height){
	var baseEduCreCourseUrl = $("#baseEduCreCourseUrl").val();
	if(baseEduCreCourseUrl == ""){
		return;
	}
	openPop({
        weburl: baseEduCreCourseUrl,
        width: width,
        height: height,
        _function: baseEduCreCourseRefer
    });
}

function baseEduCreCourseRefer(params){
	closeParentMask();
	layer.close(params.layerindex);
    window.location.reload();
}


function ajaxCreateCourse(params) {
    var name = params.name;
    var teachers = params.teachers;
    var courseLogo = params.logo;
    if (name.trim() == "" || teachers.trim() == "") {
        publicTips('failure', '名称不能为空');
        return;
    }
    var semesterType = params.semesterType;
    var semesterName = params.semesterName;
    var semesterId = params.semesterId;
	var creteaerId = params.createrId;
    var allSemesterName = params.allSemesterName;
    var catalogid = $("#courseFolderId").val();
    $.ajax({
        type: "post",
        url: _HOST_CP2_ + "/mycourse/createcourse",
        data: {
            name: name,
            teachers: teachers,
            courselogo: courseLogo,
            catalogid: catalogid,
            semesterType: semesterType,
            semesterName: semesterName,
            semesterId: semesterId,
			personId: creteaerId,
            allSemesterName: allSemesterName
        },
        success: function (data) {//如果调用成功
            var data = eval("(" + data + ")");
            if (data.status) {
                publicTips('success', '新建课程成功');
				closeParentMask();
                layer.close(params.layerindex);
                window.location.reload();
            } else {
                publicTips('failure', data.msg);
            }
        }
    });
}

