var layer, pLayui;
function getLayer() {
    pLayui = layui;
    pLayui.use(['layer'], function () {
        layer = pLayui.layer;
    });
}

var iframeData = '';
try {
    window.parent.postMessage('', '*'); //进入页面建立通信
    window.addEventListener('message', function (e) {
        if (e.data && e.data !== '') {
            iframeData = JSON.parse(e.data);
        }
    }, false);
}catch (ex) {
    console.log(ex)
}

function closeParentMask() {
    if (parent && parent.window) {
        try {
            var messageTemp = {
                "cmd": 1,
                "toggle": false
            }
            window.parent.postMessage(JSON.stringify(messageTemp), '*');
        } catch (ex) {
            console.log("关闭上层遮罩消息发送失败: " + ex)
        }
    }
}

var openParentMask = function (color) {
    if (parent && parent.window) {
        try {
            var messageTemp = {
                "cmd": 1,
                "toggle": true,
                "color": color || "rgba(16,26,41,0.76)"
            }
            window.parent.postMessage(JSON.stringify(messageTemp), '*');
        } catch (ex) {
            console.log("打开上层遮罩消息发送失败: " + ex)
        }
    }
}

function getOffset(width, height) {
    var offset = ['20%', '30%'];
    var pos = getPos(width, height);
    if (undefined != pos) {
        offset = [pos.top + 'px', pos.left + 'px'];
    }
    return offset;
}

function getPos(width, height) {
    if (window.top != window.self) {
        var left = ($(window.parent.document.body).width() - width) / 2;
        var top = ($(window.parent).height() - height) / 2;

        // var top = ($(window.parent).height() - height) / 2 + $(window.parent).scrollTop();

        return {'left': left, 'top': top};
    } else {
        var left = ($(window.document.body).width() - width) / 2;
        var top = ($(window).height() - height) / 2;
        return {'left': left, 'top': top};
        // return undefined;
    }
}

function openFirstPagePop( type, width, height, clazzId, courseId, personId, fileId, callBackMethod){
	var weburl = location.protocol + "//" + location.hostname + _HOST_CP2_ + "/visit/course/homepagepopup?type="+type;
	openPop({
        weburl: weburl,
        width: width,
        height: height,
        clazzId: clazzId,
        personId: personId,
        courseId: courseId,
        fileId : fileId,
        type: type,
        _function: callBackMethod
    });
}

function openFirstPagePopV3( type, width, height, dropClazzRecordId, callBackMethod){
	var weburl = location.protocol + "//" + location.hostname + _HOST_CP2_ + "/visit/course/homepagepopup?type="+type;
	openPop({
        weburl: weburl,
        width: width,
        height: height,
        dropClazzRecordId: dropClazzRecordId,
        type: type,
        _function: callBackMethod
    });
}

function openFirstPagePop2( type, width, height, clazzId, courseId, personId, oldFileid, newFolderCallBack, callBackMethod){
	var weburl = location.protocol + "//" + location.hostname + _HOST_CP2_ + "/visit/course/homepagepopup?type="+type;
	openPop({
        weburl: weburl,
        width: width,
        height: height,
        clazzId: clazzId,
        personId: personId,
        courseId: courseId,
        type: type,
        oldFileid:oldFileid,
        _function: callBackMethod,
        _function2: newFolderCallBack
    });
}

function openPop(options) {
    var area = [options.width + 'px', options.height + 'px'];
    var offset;
    if (options.offset != undefined) {
        offset = options.offset;
    } else {
        // offset = getOffset(options.width, options.height);
    }
    var index = layer.open({
        offset: offset,
        resize: false,
        closeBtn: false,
        shadeClose: false,
        title: false,
        area: area,
        shade: [0.76, '#101a29'],
        success: function (layero, index) {
            var chWindow = layero.find("iframe")[0].contentWindow;
            chWindow.parentlayero = layero;
            chWindow.layerindex = index;
            chWindow.player = layer;
            chWindow.parentJquery = $;
            chWindow.paramObj = options;
            chWindow.init();
            chWindow.offset = offset;
            if(options.type == 4){
	            chWindow.newFolderCallBack = function (param,name) {
	                options._function2(param,name);
	            };
	        }
            chWindow.callBak = function (param) {
                options._function(param);
            }
        },
        type: 2,
        content: options.weburl
    });

    layer.style(index, {
        "border-radius": "10px",
        "margin-top": -iframeData.paddingT / 2 + "px", "margin-left": -iframeData.paddingL / 2 + "px"
    });

    openParentMask("rgba(16, 26, 41, 0.76)");
}

