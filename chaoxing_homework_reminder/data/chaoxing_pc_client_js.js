function addTchCourse2Client(courseId,courseName,imageUrl) {
	try {
		var data = {};
		data.name = courseName;
		data.id = courseId;
		data.imageurl = imageUrl;

		jsBridge.postNotification('CLIENT_RES_RECENTLY', {
			"cataid": 100000002,
			"key": "tea_"+courseId,
			"content": data
		});

	} catch (e) {
		console.log(e);
	}
}

function addStuCourse2Client(courseId,courseName,clazzId,clazzName,cpi,imageUrl) {
	try {
		var data = {};
		data.name = clazzName;
		data.id = clazzId;
		data.cpi = cpi;
		data.course ={};
		data.course.data = [];

		var courseInfo = {};
		courseInfo.name = courseName;
		courseInfo.id = courseId;
		courseInfo.imageurl = imageUrl;
		data.course.data.push(courseInfo);

		jsBridge.postNotification('CLIENT_RES_RECENTLY', {
			"cataid": 100000002,
			"key": clazzId,
			"content": data
		});
	} catch (e) {
		console.log(e);
	}
}